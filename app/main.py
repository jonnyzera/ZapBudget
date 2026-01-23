from fastapi import FastAPI, Depends, HTTPException
from supabase import create_client, Client
from app.core.config import settings
from app.routes import budgets, auth

app = FastAPI(title="ZapBudget API")

# Rotas
app.include_router(auth.router, prefix="/auth", tags=["Autenticação"])
app.include_router(budgets.router, prefix="/budgets", tags=["Orçamentos"])

@app.get("/")
async def root():
    return {"message": "ZapBudget API está online"}