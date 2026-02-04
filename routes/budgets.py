from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from fpdf import FPDF
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Configuração do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class ZapBudgetPDF(FPDF):
    def header(self):
        # Detalhe visual: Barra verde no topo
        self.set_fill_color(22, 163, 74) 
        self.rect(0, 0, 210, 4, 'F')
        
    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(160, 174, 192)
        self.cell(0, 10, "Documento Oficial Gerado via ZapBudget Pro - Guarulhos, SP", align="C")

@router.get("/{budget_id}/pdf")
async def generate_pdf(budget_id: str):
    try:
        # 1. Busca os dados no Supabase
        res = supabase.table("orçamentos").select("*").eq("id", budget_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        
        b = res.data[0]

        # 2. Configurações do Documento
        pdf = ZapBudgetPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=20)
        
        # Cabeçalho da Empresa
        pdf.set_y(15)
        pdf.set_font("helvetica", "B", 22)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 10, b['vendor_name'].upper(), ln=True)
        
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(22, 163, 74)
        pdf.cell(0, 5, "PROPOSTA DE ORÇAMENTO COMERCIAL", ln=True)
        
        pdf.ln(15)
        
        # Bloco do Cliente (Fundo Cinza)
        pdf.set_fill_color(248, 250, 252)
        pdf.rect(10, pdf.get_y(), 190, 22, 'F')
        pdf.set_x(15)
        pdf.set_font("helvetica", "B", 8)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(0, 8, "DESTINATÁRIO", ln=True)
        pdf.set_x(15)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 6, b['client_name'], ln=True)
        
        pdf.ln(18)
        
        # Descrição dos Serviços
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(0, 10, "DETALHAMENTO DOS SERVIÇOS", ln=True)
        
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(51, 65, 85)
        pdf.multi_cell(0, 6, b['servicos'])
        
        pdf.ln(15)
        
        # Rodapé de Valores e Prazos (Simulando o Grid do site)
        y_atual = pdf.get_y()
        pdf.line(10, y_atual, 200, y_atual) # Linha divisória
        pdf.ln(5)
        
        # Coluna 1: Prazos
        pdf.set_font("helvetica", "B", 8)
        pdf.set_text_color(148, 163, 184)
        pdf.cell(95, 5, "PRAZO E PAGAMENTO", ln=0)
        # Coluna 2: Valor
        pdf.cell(95, 5, "INVESTIMENTO TOTAL", ln=1, align="R")
        
        pdf.set_font("helvetica", "B", 10)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(95, 6, f"Entrega: {b.get('prazo') or 'A combinar'}", ln=0)
        
        # Valor em destaque
        pdf.set_font("helvetica", "B", 22)
        pdf.cell(95, 6, b['valor'], ln=1, align="R")
        
        pdf.set_font("helvetica", "B", 10)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(95, 6, f"Forma: {b.get('pagamento') or 'A combinar'}", ln=0)

        # 3. Retorno do Arquivo
        pdf_output = pdf.output()
        return Response(
            content=pdf_output,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=ZapBudget_{budget_id}.pdf"}
        )
    except Exception as e:
        print(f"Erro PDF: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao gerar PDF.")