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

# --- ROTA DE CADASTRO (DEBUG) ---
@app.post("/api/auth/signup")
async def signup_manual(user: UserSignUp):
    if not supabase:
        raise HTTPException(status_code=500, detail="Erro interno: Banco de dados desconectado.")
    
    clean_cpf = user.cpf.replace(".", "").replace("-", "")
    if len(clean_cpf) != 11 or not clean_cpf.isdigit():
        raise HTTPException(status_code=400, detail="CPF inválido. Digite 11 números.")

    try:
        # Tenta verificar CPF. Se a coluna não existir, captura o erro para não travar feio.
        try:
            check_cpf = supabase.table("profiles").select("id").eq("cpf", clean_cpf).execute()
            if check_cpf.data:
                raise HTTPException(status_code=400, detail="Este CPF já está em uso.")
        except Exception as e:
            err_str = str(e).lower()
            if "column" in err_str and "does not exist" in err_str:
                print("ERRO: Coluna CPF não criada no Supabase.")
                # Se não criou a coluna, deixamos passar o cadastro sem checar CPF para não travar o usuário
                pass 
            else:
                raise e

        # Cria usuário Auth
        try:
            auth_res = supabase.auth.sign_up({
                "email": user.email,
                "password": user.password,
                "options": { "data": { "full_name": user.name, "cpf": clean_cpf } }
            })
            
            if not auth_res.user:
                 raise HTTPException(status_code=400, detail="Erro ao criar conta. E-mail pode já existir.")
            
            if auth_res.user.identities is not None and len(auth_res.user.identities) == 0:
                 raise HTTPException(status_code=400, detail="Este e-mail já está cadastrado.")

        except Exception as auth_error:
            msg = str(auth_error).lower()
            if "already registered" in msg:
                raise HTTPException(status_code=400, detail="E-mail já cadastrado. Faça login.")
            raise auth_error 

        # Cria Perfil
        supabase.table("profiles").upsert({
            "id": auth_res.user.id,
            "full_name": user.name,
            "cpf": clean_cpf,
            "trial_start": datetime.now(timezone.utc).isoformat(),
            "is_premium": False,
            "provider": "email"
        }).execute()

        return {"status": "success"}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro Signup: {e}")
        raise HTTPException(status_code=400, detail="Erro ao processar. Tente novamente.")

# --- DEMAIS ROTAS ---
@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET: raise HTTPException(status_code=500, detail="No Stripe Secret") 
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook Error: {e}")
    
    if not supabase: return {"status": "ignored"}

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        uid = session.get('client_reference_id')
        if uid: supabase.table("profiles").update({"is_premium": True, "stripe_customer_id": session.get('customer')}).eq("id", uid).execute()
    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.updated']:
        sub = event['data']['object']
        if sub.get('status') != 'active':
            res = supabase.table("profiles").select("id").eq("stripe_customer_id", sub['customer']).execute()
            if res.data: supabase.table("profiles").update({"is_premium": False}).eq("id", res.data[0]['id']).execute()
    return {"status": "success"}

@app.post("/api/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    if not supabase: raise HTTPException(status_code=500, detail="DB Error")
    try:
        res_p = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        if not res_p.data:
            new_p = {"id": dados.user_id, "trial_start": datetime.now(timezone.utc).isoformat(), "is_premium": False, "provider": "email"}
            supabase.table("profiles").insert(new_p).execute()
            p = new_p
        else: p = res_p.data[0]

        if not p.get("is_premium"):
            trial = datetime.fromisoformat(p["trial_start"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > (trial + timedelta(days=7)):
                raise HTTPException(status_code=402, detail="Teste expirado.")

        pl = dados.model_dump(exclude_none=True)
        if "validade" in pl and not pl["validade"]: pl["validade"] = None
        
        res = supabase.table("orçamentos").insert(pl).execute()
        return {"id": res.data[0]['id']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orcamentos/{id}")
async def buscar_orcamento(id: str):
    if not supabase: raise HTTPException(status_code=500, detail="DB Error")
    res = supabase.table("orçamentos").select("*").eq("id", id).execute()
    if not res.data: raise HTTPException(status_code=404, detail="Não encontrado")
    return res.data[0]

@app.get("/api/health")
def health(): return {"status": "ok"}

public_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if os.path.exists(public_path):
    app.mount("/", StaticFiles(directory=public_path, html=True), name="public")