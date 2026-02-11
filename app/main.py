from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
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

@app.get("/")
def read_root():
    return RedirectResponse(url="/index.html")

# Configuração de Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://zapbudget.com.br", 
        "https://www.zapbudget.com.br",
        "http://localhost:3000",
        "https://zapbudget.vercel.app"
    ],
    allow_origin_regex=r"https://zapbudget-.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro do endpoint de PDF
if budgets:
    app.include_router(budgets.router, prefix="/api/v1/pdf", tags=["PDF"])

# --- CONFIGURAÇÃO DE DIRETÓRIOS ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)

# Credenciais Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("AVISO: Variáveis SUPABASE não configuradas.")
else:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Modelo de Dados
class Orcamento(BaseModel):
    user_id: str
    vendor_name: str
    client_name: str
    servicos: str
    valor: str
    prazo: str = None
    pagamento: str = None
    validade: str = None 

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
        # Busca o perfil do usuário
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            # Se o perfil não existir (ex: primeiro orçamento), cria um novo
            # Nota: O campo 'provider' será preenchido como 'email' por padrão aqui, 
            # mas o login.html cuidará de atualizar para 'google' se necessário.
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

        # Verificação de Trial (7 dias)
        if not profile.get("is_premium", False):
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            if datetime.now(timezone.utc) > (trial_start + timedelta(days=7)):
                raise HTTPException(status_code=402, detail="Teste expirado.")

        # Insere o orçamento
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

# --- ROTAS PARA ARQUIVOS ESTÁTICOS ---
@app.get("/api/manifest.json")
async def serve_manifest():
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

@app.get("/api/service-worker.js")
async def serve_sw():
    return FileResponse(os.path.join(ROOT_DIR, "service-worker.js"))

# Export para a Vercel
app = app