from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os

app = FastAPI()

# Permite que o seu site aceda à API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credenciais do Supabase
SUPABASE_URL = "SUA_URL_DO_SUPABASE"
SUPABASE_KEY = "SUA_KEY_DO_SUPABASE"
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