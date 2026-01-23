from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import os

app = FastAPI()

# Permite que seu site (frontend) acesse esta API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, coloque o domínio do seu site
    allow_methods=["*"],
    allow_headers=["*"],
)

# Substitua pelas credenciais que aparecem em Settings > API no seu Supabase
SUPABASE_URL = "SUA_URL_AQUI"
SUPABASE_KEY = "SUA_CHAVE_ANON_PUBLIC_AQUI"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Modelo de dados que a API espera receber
class Orcamento(BaseModel):
    vendor_name: str
    client_name: str
    servicos: str
    valor: str
    prazo: str = None
    pagamento: str = None
    validade: str = None

@app.post("/salvar-orcamento")
async def salvar(dados: Orcamento):
    try:
        # Insere os dados na tabela que você criou no Supabase
        res = supabase.table("orçamentos").insert(dados.dict()).execute()
        
        # Retorna o ID do orçamento recém-criado
        return {"id": res.data[0]['id']}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orcamento/{id}")
async def buscar(id: str):
    try:
        # Busca um orçamento específico pelo ID
        res = supabase.table("orçamentos").select("*").eq("id", id).single().execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")