from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from app.routes import budgets

# Carrega as variáveis do ficheiro .env
load_dotenv()

app = FastAPI()

# Configuração de CORS para permitir acesso do PWA (Frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro essencial para o funcionamento do endpoint de PDF
app.include_router(budgets.router, prefix="/api/v1/pdf", tags=["PDF"])

# Caminho para a pasta de templates/estáticos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
# O manifest e o service worker costumam estar na raiz do projeto (zapbudget/)
ROOT_DIR = os.path.dirname(BASE_DIR)

# Monta a pasta de arquivos estáticos (para imagens, css, js)
if os.path.exists(TEMPLATES_DIR):
    app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")

# Credenciais Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Erro: Variáveis de ambiente SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")

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

# --- ROTAS DE NAVEGAÇÃO E PWA (Prioridade Máxima) ---

@app.get("/")
async def serve_home():
    """Serve o site.html como página principal para priorizar o PWA"""
    site_path = os.path.join(TEMPLATES_DIR, "site.html")
    if os.path.exists(site_path):
        return FileResponse(site_path)
    
    # Fallback para index caso site.html não exista
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    return {"message": "ZapBudget API ativa. Frontend não encontrado."}

@app.get("/manifest.json")
async def serve_manifest():
    """Serve o ficheiro manifest.json necessário para o PWA ser instalável"""
    manifest_path = os.path.join(ROOT_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path)
    return HTTPException(status_code=404)

@app.get("/service-worker.js")
async def serve_sw():
    """Serve o ficheiro service-worker.js necessário para o PWA"""
    sw_path = os.path.join(ROOT_DIR, "service-worker.js")
    if os.path.exists(sw_path):
        return FileResponse(sw_path)
    return HTTPException(status_code=404)

@app.get("/favicon.ico")
async def favicon():
    """Serve o favicon para evitar erro 404 no log"""
    favicon_path = os.path.join(TEMPLATES_DIR, "img", "favicon (3).png")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return HTTPException(status_code=404)

# --- ROTAS DA API ---

@app.post("/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    try:
        # 1. Verificar/Criar o perfil do utilizador
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            # Novo utilizador: Criação de trial automático de 7 dias
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "is_premium": False
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data[0]

        # 2. Validar período de 7 dias ou Assinatura Premium
        if not profile.get("is_premium", False):
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            agora = datetime.now(timezone.utc)

            if agora > (trial_start + timedelta(days=7)):
                raise HTTPException(
                    status_code=402, 
                    detail="O seu período de 7 dias grátis terminou. Assine o Pro para continuar!"
                )

        # 3. Guardar o orçamento no banco de dados
        payload = dados.model_dump(exclude_none=True)
        res_budget = supabase.table("orçamentos").insert(payload).execute()
        
        if not res_budget.data:
             raise HTTPException(status_code=500, detail="Erro ao guardar no banco de dados")
             
        return {"id": res_budget.data[0]['id']}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro no Servidor: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno no servidor")

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    try:
        res = supabase.table("orçamentos").select("*").eq("id", id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        return res.data[0]
    except HTTPException as he:
        raise he
    except Exception:
        raise HTTPException(status_code=404, detail="Erro ao buscar orçamento")