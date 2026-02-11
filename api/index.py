import sys
import os

# Adiciona o diretório pai (raiz do projeto) ao caminho do Python
# Isso resolve o erro "ModuleNotFoundError: No module named 'app'"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

# Este arquivo é o ponto de entrada para a Vercel.