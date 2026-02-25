import os
import stripe
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from supabase import create_client
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()
app = FastAPI()

# --- IMPORTAÇÃO DE ROTAS (PDF) ---
try:
    from app.routes import budgets
except ImportError:
    try:
        from routes import budgets
    except ImportError:
        budgets = None

# --- CONFIGURAÇÃO CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INTEGRAÇÕES ---
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Erro Supabase: {e}")

if budgets:
    app.include_router(budgets.router, prefix="/api/orcamentos", tags=["PDF"])

# --- MODELOS ---
class Orcamento(BaseModel):
    user_id: str
    vendor_name: str
    client_name: str
    servicos: str
    valor: str
    prazo: Optional[str] = None
    pagamento: Optional[str] = None
    validade: Optional[str] = None 

class UserSignUp(BaseModel):
    name: str
    email: EmailStr
    cpf: str
    password: str

# --- ROTA DE CADASTRO ---
@app.post("/api/auth/signup")
async def signup_manual(user: UserSignUp):
    if not supabase:
        raise HTTPException(status_code=500, detail="Erro interno: Banco de dados desligado.")
    
    clean_cpf = user.cpf.replace(".", "").replace("-", "")
    if len(clean_cpf) != 11 or not clean_cpf.isdigit():
        raise HTTPException(status_code=400, detail="CPF inválido. Digite apenas os 11 números.")

    # 1. VERIFICAR SE O CPF JÁ EXISTE
    try:
        check_cpf = supabase.table("profiles").select("id").eq("cpf", clean_cpf).execute()
        if check_cpf.data and len(check_cpf.data) > 0:
            raise HTTPException(status_code=400, detail="Este CPF já está em uso em outra conta.")
    except Exception as e:
        err_str = str(e).lower()
        if "column" not in err_str or "does not exist" not in err_str:
            raise HTTPException(status_code=500, detail="Erro de conexão ao verificar o CPF.")

    # 2. CRIAR O UTILIZADOR NO SUPABASE AUTH
    try:
        auth_res = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password,
            "options": { "data": { "full_name": user.name, "cpf": clean_cpf } }
        })
        
        if not auth_res.user:
             raise HTTPException(status_code=400, detail="Não foi possível criar a conta.")

    except Exception as auth_error:
        msg = str(auth_error).lower()
        if "already registered" in msg:
            raise HTTPException(status_code=400, detail="Este E-mail já está em uso. Faça Login.")
        elif "password should be at least 6 characters" in msg:
            raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 6 caracteres.")
        raise HTTPException(status_code=400, detail=str(auth_error))

    # 3. SALVAR NA TABELA PROFILES (Inicia o Trial de 7 dias)
    try:
        supabase.table("profiles").upsert({
            "id": auth_res.user.id,
            "full_name": user.name,
            "cpf": clean_cpf,
            "trial_start": datetime.now(timezone.utc).isoformat(),
            "is_premium": False,
            "provider": "email"
        }).execute()
    except Exception as e:
        print(f"Erro ao salvar profile: {e}")

    return {"status": "success", "message": "Conta criada com sucesso"}

# --- WEBHOOK STRIPE (ATIVAÇÃO AUTOMÁTICA) ---
@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET: 
        raise HTTPException(status_code=500, detail="Configuração de Webhook ausente.") 
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro de assinatura: {e}")
    
    if not supabase: return {"status": "ignored"}

    # Pagamento Confirmado -> Ativa o acesso Premium
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        uid = session.get('client_reference_id') 
        cid = session.get('customer')
        
        if uid:
            supabase.table("profiles").update({
                "is_premium": True, 
                "stripe_customer_id": cid
            }).eq("id", uid).execute()

    # Assinatura Cancelada -> Remove o acesso Premium
    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.updated']:
        sub = event['data']['object']
        if sub.get('status') != 'active':
            res = supabase.table("profiles").select("id").eq("stripe_customer_id", sub['customer']).execute()
            if res.data:
                supabase.table("profiles").update({"is_premium": False}).eq("id", res.data[0]['id']).execute()
    
    return {"status": "success"}

# --- ROTA DE ORÇAMENTOS (COM BLOQUEIO DE TRIAL) ---
@app.post("/api/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    if not supabase: raise HTTPException(status_code=500, detail="Erro no Banco de Dados")
    
    try:
        # 1. Verificar perfil e status de pagamento
        res_p = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_p.data:
            raise HTTPException(status_code=404, detail="Perfil não encontrado.")
        
        p = res_p.data[0]

        # 2. Lógica de Bloqueio Estrita: Se não for Premium, verifica se o Trial de 7 dias expirou
        if not p.get("is_premium"):
            trial_str = p["trial_start"].replace("Z", "+00:00")
            trial_date = datetime.fromisoformat(trial_str)
            
            if datetime.now(timezone.utc) > (trial_date + timedelta(days=7)):
                # Retorna 402 para o Frontend disparar o modal de pagamento
                raise HTTPException(status_code=402, detail="O seu período de teste expirou. Assine o PRO para continuar.")

        # 3. Salvar orçamento se autorizado
        pl = dados.model_dump(exclude_none=True)
        if "validade" in pl and not pl["validade"]: pl["validade"] = None
        
        res = supabase.table("orçamentos").insert(pl).execute()
        return {"id": res.data[0]['id']}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- DEMAIS ROTAS ---
@app.get("/api/orcamentos/{id}")
async def buscar_orcamento(id: str):
    if not supabase: raise HTTPException(status_code=500, detail="Erro no Banco de Dados")
    res = supabase.table("orçamentos").select("*").eq("id", id).execute()
    if not res.data: raise HTTPException(status_code=404, detail="Não encontrado")
    return res.data[0]

@app.get("/api/health")
def health(): return {"status": "ok"}

# Montar arquivos estáticos
public_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if os.path.exists(public_path):
    app.mount("/", StaticFiles(directory=public_path, html=True), name="public")