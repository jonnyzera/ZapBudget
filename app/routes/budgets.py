from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from weasyprint import HTML
import tempfile

router = APIRouter()

@router.get("/{budget_id}/pdf")
async def generate_pdf(budget_id: str):
    try:
        # 1. Aqui você buscaria os dados do Supabase usando o budget_id
        # 2. Renderizaria um template HTML com esses dados
        html_content = f"<h1>Orçamento {budget_id}</h1><p>Dados do orçamento aqui...</p>"
        
        # 3. Gerar o PDF
        pdf = HTML(string=html_content).write_pdf()
        
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=orcamento_{budget_id}.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))