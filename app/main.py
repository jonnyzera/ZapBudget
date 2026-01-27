from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

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

# Credenciais Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Erro: Variáveis de ambiente SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não encontradas.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Modelo de Dados - Corrigido 'validate' para 'validade' para evitar conflito com Pydantic
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
        # 1. Verificar/Criar o perfil do utilizador (Uso do execute() para evitar exceções se não existir)
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).execute()
        
        if not res_profile.data:
            # Novo usuário: Inicia Trial de 7 dias
            new_profile = {
                "id": dados.user_id,
                "trial_start": datetime.now(timezone.utc).isoformat(),
                "is_premium": False
            }
            supabase.table("profiles").insert(new_profile).execute()
            profile = new_profile
        else:
            profile = res_profile.data[0]

        # 2. Validar período de Trial ou Assinatura Premium
        if not profile.get("is_premium", False):
            # Normalização da data (ISO para objeto datetime)
            start_str = profile["trial_start"].replace("Z", "+00:00")
            trial_start = datetime.fromisoformat(start_str)
            agora = datetime.now(timezone.utc)

            if agora > (trial_start + timedelta(days=7)):
                raise HTTPException(
                    status_code=402, 
                    detail="O seu período de 7 dias grátis terminou. Assine o Pro para continuar!"
                )

        # 3. Guardar o orçamento no banco de dados
        # .model_dump() é o padrão do Pydantic v2 (substituto do .dict())
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
        # Busca orçamento único
        res = supabase.table("orçamentos").select("*").eq("id", id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        return res.data[0]
    except HTTPException as he:
        raise he
    except Exception:
        raise HTTPException(status_code=404, detail="Erro ao buscar orçamento")