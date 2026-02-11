from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from supabase import create_client
import os
import stripe
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Importação das rotas de PDF
try:
    from app.routes import budgets
except ImportError:
    budgets = None

# Carrega as variáveis de ambiente
load_dotenv()

app = FastAPI()

# --- CONFIGURAÇÃO DE CORS (CORRIGIDA) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zapbudget.com.br", 
        "https://www.zapbudget.com.br",
        "http://localhost:3000",
        "https://zapbudget.vercel.app", # Vírgula adicionada para evitar erro de sintaxe
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURAÇÃO DE DIRETÓRIOS E CLIENTES ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)

# Configuração de Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Credenciais Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("AVISO: Variáveis SUPABASE não configuradas.")
else:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- MODELOS DE DADOS ---

class Orcamento(BaseModel):
    user_id: str
    vendor_name: str
    client_name: str
    servicos: str
    valor: str
    prazo: str = None
    pagamento: str = None
    validade: str = None 

# Novo modelo para o Cadastro Manual (E-mail, CPF, Senha)
class UserSignUp(BaseModel):
    name: str
    email: EmailStr
    cpf: str
    password: str

# --- ROTAS DE AUTENTICAÇÃO ---

@app.post("/api/auth/signup")
async def signup_manual(user: UserSignUp):
    try:
        # 1. Verificar se o CPF já existe na tabela profiles para evitar duplicidade
        check_cpf = supabase.table("profiles").select("id").eq("cpf", user.cpf).execute()
        if check_cpf.data:
            raise HTTPException(status_code=400, detail="Este CPF já está cadastrado.")

        # 2. Criar usuário no Supabase Auth
        # O Supabase já valida nativamente se o e-mail é único
        auth_res = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password,
            "options": {
                "data": {
                    "full_name": user.name,
                    "cpf": user.cpf
                }
            }
        })

        if not auth_res.user:
            raise HTTPException(status_code=400, detail="Erro ao criar conta de autenticação.")

        # 3. Criar o perfil na sua tabela 'profiles' para controle de trial/premium
        supabase.table("profiles").upsert({
            "id": auth_res.user.id,
            "full_name": user.name,
            "cpf": user.cpf,
            "trial_start": datetime.now(timezone.utc).isoformat(),
            "is_premium": False,
            "provider": "email"
        }).execute()

        return {"status": "success", "message": "Conta criada com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- ROTAS DE PAGAMENTO (STRIPE WEBHOOK) ---

@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro no Webhook: {str(e)}")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('client_reference_id')
        
        if user_id:
            supabase.table("profiles").update({
                "is_premium": True,
                "stripe_customer_id": session.get('customer')
            }).eq("id", user_id).execute()

    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.updated']:
        subscription = event['data']['object']
        if subscription.get('status') != 'active':
            res = supabase.table("profiles").select("id").eq("stripe_customer_id", subscription['customer']).execute()
            if res.data:
                supabase.table("profiles").update({"is_premium": False}).eq("id", res.data[0]['id']).execute()

    return {"status": "success"}

# --- ROTAS DA API DE ORÇAMENTOS ---

@app.post("/api/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    try:
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "is_premium": False,
                "provider": "email" 
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data[0]

        if not profile.get("is_premium", False):
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            if datetime.now(timezone.utc) > (trial_start + timedelta(days=7)):
                raise HTTPException(status_code=402, detail="Teste expirado.")

        payload = dados.model_dump(exclude_none=True)
        res_budget = supabase.table("orçamentos").insert(payload).execute()
        
        if not res_budget.data:
            raise HTTPException(status_code=500, detail="Erro ao salvar no banco.")
            
        return {"id": res_budget.data[0]['id']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orcamentos/{id}")
async def buscar_orcamento(id: str):
    try:
        res = supabase.table("orçamentos").select("*").eq("id", id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Não encontrado")
        return res.data[0]
    except Exception:
        raise HTTPException(status_code=404, detail="Erro ao buscar orçamento")

# --- ROTAS GERAIS E PDF ---

if budgets:
    app.include_router(budgets.router, prefix="/api/v1/pdf", tags=["PDF"])

@app.get("/")
def read_root():
    return FileResponse(os.path.join(ROOT_DIR, "public", "index.html"))

@app.get("/api/manifest.json")
async def serve_manifest():
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

@app.get("/api/service-worker.js")
async def serve_sw():
    return FileResponse(os.path.join(ROOT_DIR, "service-worker.js"))

app = app