import openai
from openai import OpenAI
import google.generativeai as genai
import PyPDF2
import json
import io
import os
from datetime import datetime
from expense_classifier import ExpenseClassifier
from typing import Dict, Optional

class PDFProcessor:
    def __init__(self):
        """
        Inicializa o processador de PDF com cliente OpenAI e Gemini
        """
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        # Configurar Gemini como fallback (sem listar modelos para evitar chamadas remotas no startup)
        gemini_key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        self.gemini_model = None
        if gemini_key:
            genai.configure(api_key=gemini_key)
            preferred = os.getenv('GEMINI_MODEL_NAME')
            candidates = [preferred] if preferred else [
                "gemini-1.5-flash-001",
                "gemini-1.5-flash-latest",
                "gemini-1.5-pro-001",
                "gemini-1.5-pro-latest",
                "gemini-pro"
            ]
            for candidate in [m for m in candidates if m]:
                try:
                    self.gemini_model = genai.GenerativeModel(candidate)
                    break
                except Exception as e:
                    print(f"Falha ao inicializar Gemini com modelo '{candidate}': {e}")
        else:
            self.gemini_model = None
            
        self.classifier = ExpenseClassifier()
    
    def extract_text_from_pdf(self, pdf_file) -> str:
        """
        Extrai texto de um arquivo PDF
        """
        try:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
        except Exception as e:
            raise Exception(f"Erro ao extrair texto do PDF: {str(e)}")
    
    def extract_invoice_data(self, pdf_text: str) -> dict:
        """
        Extrai dados estruturados da nota fiscal usando OpenAI GPT
        """
        prompt = f"""
        Você é um especialista em extração de dados de notas fiscais brasileiras.
        
        Analise o texto da nota fiscal abaixo e extraia EXATAMENTE as seguintes informações em formato JSON:
        
        {{
            "fornecedor": {{
                "razao_social": "string",
                "fantasia": "string ou null",
                "cnpj": "string (formato XX.XXX.XXX/XXXX-XX)"
            }},
            "faturado": {{
                "nome_completo": "string",
                "cpf": "string (formato XXX.XXX.XXX-XX)"
            }},
            "numero_nota_fiscal": "string",
            "data_emissao": "string (formato YYYY-MM-DD)",
            "descricao_produtos": "string (descrição detalhada de todos os produtos/serviços)",
            "valor_total": "number (valor decimal)",
            "data_vencimento": "string (formato YYYY-MM-DD)",
            "quantidade_parcelas": 1
        }}
        
        REGRAS IMPORTANTES:
        1. Se algum campo não for encontrado, use null
        2. Para datas, converta para o formato YYYY-MM-DD
        3. Para valores monetários, use apenas números (sem símbolos)
        4. Para CNPJ e CPF, mantenha a formatação com pontos e traços
        5. Na descrição dos produtos, inclua TODOS os itens listados na nota
        
        Texto da nota fiscal:
        {pdf_text}
        
        Responda APENAS com o JSON válido:
        """
        
        try:
            response = self.client.completions.create(
                model="gpt-3.5-turbo-instruct",
                prompt=prompt,
                max_tokens=1000,
                temperature=0.1
            )
            
            json_response = response.choices[0].text.strip()
            
            # Tentar parsear o JSON
            try:
                data = json.loads(json_response)
            except json.JSONDecodeError:
                # Se falhar, tentar limpar o texto
                json_response = json_response.replace("```json", "").replace("```", "").strip()
                data = json.loads(json_response)
            
            # Classificar a despesa automaticamente
            if data.get("descricao_produtos"):
                classificacao = self.classifier.classify_expense(data["descricao_produtos"])
                data["classificacao_despesa"] = classificacao
            
            return data
            
        except Exception as e:
            error_message = str(e)
            
            # Tratamento específico para erros de quota da OpenAI
            if "quota" in error_message.lower() or "exceeded" in error_message.lower():
                print(f"OpenAI quota exceeded, trying Gemini fallback...")
                return self._extract_with_gemini(prompt)
            elif "rate limit" in error_message.lower():
                print(f"OpenAI rate limit reached, trying Gemini fallback...")
                return self._extract_with_gemini(prompt)
            elif "authentication" in error_message.lower() or "api key" in error_message.lower():
                print(f"OpenAI authentication error, trying Gemini fallback...")
                return self._extract_with_gemini(prompt)
            else:
                # Para outros erros, tentar Gemini como fallback
                print(f"OpenAI error: {error_message}, trying Gemini fallback...")
                return self._extract_with_gemini(prompt)
    
    def _extract_with_gemini(self, prompt: str) -> dict:
        """
        Extrai dados usando Google Gemini como fallback
        """
        if not (os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')):
            raise Exception("Erro na extração de dados: OpenAI indisponível e Gemini não configurado. Verifique as chaves de API.")
        
        candidates = [
            os.getenv('GEMINI_MODEL_NAME'),
            "gemini-1.5-flash-001",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash",
            "gemini-1.5-pro-001",
            "gemini-1.5-pro-latest",
            "gemini-1.5-pro",
            "gemini-pro"
        ]
        last_error = None
        
        # Tenta candidatos diretos
        for name in [c for c in candidates if c]:
            try:
                model = genai.GenerativeModel(name)
                response = model.generate_content(prompt)
                json_response = response.text.strip()
                try:
                    data = json.loads(json_response)
                except json.JSONDecodeError:
                    json_response = json_response.replace("```json", "").replace("```", "").strip()
                    data = json.loads(json_response)
                if data.get("descricao_produtos"):
                    classificacao = self.classifier.classify_expense(data["descricao_produtos"])
                    data["classificacao_despesa"] = classificacao
                self.gemini_model = model
                return data
            except Exception as e:
                last_error = e
                continue
        
        # Se todos candidatos falharem, listar modelos e escolher um com generateContent
        try:
            available = genai.list_models()
            supported = []
            for m in available:
                methods = getattr(m, 'supported_generation_methods', []) or []
                name = getattr(m, 'name', None)
                if name and any('generateContent' == x or 'generate_content' == x for x in methods):
                    supported.append(name)
            # Preferir 1.5 se disponível
            preferred_names = [n for n in supported if 'gemini-1.5' in n] or supported
            for full_name in preferred_names:
                try:
                    model = genai.GenerativeModel(full_name)
                    response = model.generate_content(prompt)
                    json_response = response.text.strip()
                    try:
                        data = json.loads(json_response)
                    except json.JSONDecodeError:
                        json_response = json_response.replace("```json", "").replace("```", "").strip()
                        data = json.loads(json_response)
                    if data.get("descricao_produtos"):
                        classificacao = self.classifier.classify_expense(data["descricao_produtos"])
                        data["classificacao_despesa"] = classificacao
                    self.gemini_model = model
                    return data
                except Exception as e:
                    last_error = e
                    continue
        except Exception as e:
            last_error = e
        
        raise Exception(f"Erro na extração de dados: Tanto OpenAI quanto Gemini falharam. Gemini error: {str(last_error)}")
    
    def process_pdf(self, pdf_file) -> dict:
        """
        Processa um arquivo PDF completo e retorna os dados extraídos
        """
        try:
            # Extrair texto do PDF
            pdf_text = self.extract_text_from_pdf(pdf_file)
            
            if not pdf_text:
                raise Exception("Não foi possível extrair texto do PDF")
            
            # Extrair dados estruturados
            invoice_data = self.extract_invoice_data(pdf_text)
            
            # Adicionar metadados
            invoice_data["processed_at"] = datetime.now().isoformat()
            # Removido campo 'pdf_text' do retorno conforme solicitado
            
            return {
                "success": True,
                "data": invoice_data
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }