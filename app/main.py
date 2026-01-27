from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os
from datetime import datetime
from dotenv import load_dotenv

# Carrega as variáveis do ficheiro .env para o sistema
load_dotenv()

app = FastAPI()

# Configuração de CORS para permitir acesso de qualquer origem
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credenciais obtidas de forma segura através do ambiente (.env)
SUPABASE_URL = os.getenv("SUPABASE_URL")
# No backend, usamos a SERVICE_ROLE_KEY para ignorar políticas de RLS ao gerir perfis
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Erro: Variáveis de ambiente SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")

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

@app.post("/orcamentos")
async def salvar_orcamento(dados: Orcamento):
    try:
        # 1. Verificar/Criar o perfil do utilizador
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).single().execute()
        
        if not res_profile.data:
            # Criação de trial automático de 7 dias
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.utcnow().isoformat(),
                "is_premium": False
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data

        # 2. Validar período de 7 dias ou Assinatura Premium
        is_premium = profile.get("is_premium", False)
        trial_start_str = profile["trial_start"].replace("Z", "+00:00")
        trial_start = datetime.fromisoformat(trial_start_str)
        hoje = datetime.utcnow().astimezone()

        if not is_premium:
            dias_de_uso = (hoje - trial_start.astimezone()).days
            if dias_de_uso > 7:
                raise HTTPException(
                    status_code=402, 
                    detail="O seu período de 7 dias grátis terminou. Assine o Pro para continuar!"
                )

        # 3. Guardar o orçamento no banco de dados
        res_budget = supabase.table("orçamentos").insert(dados.dict()).execute()
        
        if not res_budget.data:
             raise HTTPException(status_code=500, detail="Erro ao guardar no banco de dados")
             
        return {"id": res_budget.data[0]['id']}

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    try:
        res = supabase.table("orçamentos").select("*").eq("id", id).single().execute()
        return res.data
    except Exception:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado ou link expirado")