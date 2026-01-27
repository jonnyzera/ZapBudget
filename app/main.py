from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os
from datetime import datetime, timedelta

app = FastAPI()

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credenciais do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://oqafestnsewmigjeozeh.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_hR1cOLUTK0is6yOiNfWnKQ_5xz7bDXI")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class Orcamento(BaseModel):
    user_id: str  # ID do usuário logado (obrigatório para o SaaS)
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
        # 1. Buscar o perfil do usuário para validar o acesso
        res_profile = supabase.table("profiles").select("*").eq("id", dados.user_id).single().execute()
        
        if not res_profile.data:
            # Caso o perfil não exista, podemos criar um trial automático a partir de hoje
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
        trial_start = datetime.fromisoformat(profile["trial_start"].replace("Z", "+00:00"))
        hoje = datetime.utcnow().astimezone()

        if not is_premium:
            dias_de_uso = (hoje - trial_start.astimezone()).days
            if dias_de_uso > 7:
                raise HTTPException(
                    status_code=402, 
                    detail="Seu período de 7 dias grátis acabou. Assine o Pro para continuar enviando orçamentos!"
                )

        # 3. Salvar o orçamento vinculado ao usuário
        res_budget = supabase.table("orçamentos").insert(dados.dict()).execute()
        
        if not res_budget.data:
             raise HTTPException(status_code=500, detail="Erro ao salvar no banco de dados")
             
        return {"id": res_budget.data[0]['id']}

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    try:
        # A visualização do orçamento continua pública para que o cliente possa abrir o link
        res = supabase.table("orçamentos").select("*").eq("id", id).single().execute()
        return res.data
    except Exception:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado ou link expirado")