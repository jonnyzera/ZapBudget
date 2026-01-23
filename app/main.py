from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os

app = FastAPI()

# Configuração de CORS para permitir que o front-end acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credenciais do Supabase (Usando os.getenv para segurança)
# Substitua no seu ambiente ou arquivo .env:
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://oqafestnsewmigjeozeh.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_hR1cOLUTK0is6yOiNfWnKQ_5xz7bDXI")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class Orcamento(BaseModel):
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
        # Insere na tabela 'orçamentos' e retorna o ID
        res = supabase.table("orçamentos").insert(dados.dict()).execute()
        if not res.data:
             raise HTTPException(status_code=500, detail="Erro ao inserir dados")
        return {"id": res.data[0]['id']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orcamentos/{id}")
async def buscar_orcamento(id: str):
    try:
        # Busca o orçamento pelo ID único
        res = supabase.table("orçamentos").select("*").eq("id", id).single().execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")