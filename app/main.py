from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client
import os
import stripe
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from app.routes import budgets

# Carrega as variáveis do ficheiro .env
load_dotenv()

app = FastAPI()

# Configuração de Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro do endpoint de PDF
app.include_router(budgets.router, prefix="/api/v1/pdf", tags=["PDF"])

# Caminhos de diretórios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
ROOT_DIR = os.path.dirname(BASE_DIR)

if os.path.exists(TEMPLATES_DIR):
    app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")

# Credenciais Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Erro: Variáveis SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Escuta eventos do Stripe para ativar/desativar Premium automaticamente
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro no Webhook: {str(e)}")

    # Pagamento de assinatura concluído com sucesso
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('client_reference_id')
        
        if user_id:
            supabase.table("profiles").update({
                "is_premium": True,
                "stripe_customer_id": session.get('customer')
            }).eq("id", user_id).execute()

    # Assinatura cancelada ou expirada
    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.updated']:
        subscription = event['data']['object']
        if subscription.get('status') != 'active':
            # Busca o usuário pelo ID do cliente Stripe e remove o premium
            res = supabase.table("profiles").select("id").eq("stripe_customer_id", subscription['customer']).execute()
            if res.data:
                supabase.table("profiles").update({"is_premium": False}).eq("id", res.data[0]['id']).execute()

    return {"status": "success"}

# --- ROTAS PWA E NAVEGAÇÃO ---

@app.get("/")
async def serve_home():
    site_path = os.path.join(TEMPLATES_DIR, "site.html")
    return FileResponse(site_path) if os.path.exists(site_path) else {"message": "API Ativa"}

@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(os.path.join(ROOT_DIR, "manifest.json"))

@app.get("/service-worker.js")
async def serve_sw():
    return FileResponse(os.path.join(ROOT_DIR, "service-worker.js"))

# --- ROTAS DA API ---

@app.post("/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    try:
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            # Novo utilizador: Trial automático de 7 dias
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "is_premium": False
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data[0]

        # Validação de acesso (Trial ou Premium)
        if not profile.get("is_premium", False):
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            if datetime.now(timezone.utc) > (trial_start + timedelta(days=7)):
                raise HTTPException(status_code=402, detail="Trial expirado. Assine o Pro!")

        payload = dados.model_dump(exclude_none=True)
        res_budget = supabase.table("orçamentos").insert(payload).execute()
        
        return {"id": res_budget.data[0]['id']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    res = supabase.table("orçamentos").select("*").eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    return res.data[0]