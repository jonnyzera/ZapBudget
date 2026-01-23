from fastapi import APIRouter, Header
from app.models.budget import BudgetCreate
from supabase import create_client

router = APIRouter()

@router.post("/create")
async def create_budget(budget: BudgetCreate, authorization: str = Header(None)):
    # Lógica para salvar no Supabase
    # O Supabase já lida com a persistência de forma segura
    pass

@router.get("/{budget_id}/pdf")
async def generate_pdf(budget_id: str):
    # Aqui você usaria o WeasyPrint para transformar seu HTML em PDF
    # e retornaria o arquivo para download
    pass