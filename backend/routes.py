from flask import request, jsonify
from app import app, db
from models import *
from pdf_processor import PDFProcessor
from expense_classifier import ExpenseClassifier
import os
from datetime import datetime
from decimal import Decimal

pdf_processor = PDFProcessor()
expense_classifier = ExpenseClassifier()

@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """
    Endpoint para upload e processamento de PDF
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Apenas arquivos PDF são aceitos'}), 400
        
        # Processar o PDF
        result = pdf_processor.process_pdf(file)
        
        if not result['success']:
            return jsonify({'error': result['error']}), 500
        
        return jsonify(result['data']), 200
        
    except Exception as e:
        return jsonify({'error': f'Erro interno do servidor: {str(e)}'}), 500

@app.route('/api/save-invoice', methods=['POST'])
def save_invoice():
    """
    Endpoint para salvar os dados da nota fiscal no banco
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Dados não fornecidos'}), 400
        
        # Criar ou buscar fornecedor
        fornecedor_data = data.get('fornecedor', {})
        fornecedor = Fornecedor.query.filter_by(cnpj=fornecedor_data.get('cnpj')).first()
        
        if not fornecedor:
            fornecedor = Fornecedor(
                razao_social=fornecedor_data.get('razao_social'),
                fantasia=fornecedor_data.get('fantasia'),
                cnpj=fornecedor_data.get('cnpj')
            )
            db.session.add(fornecedor)
            db.session.flush()
        
        # Criar ou buscar faturado
        faturado_data = data.get('faturado', {})
        faturado = Faturado.query.filter_by(cpf=faturado_data.get('cpf')).first()
        
        if not faturado:
            faturado = Faturado(
                nome_completo=faturado_data.get('nome_completo'),
                cpf=faturado_data.get('cpf')
            )
            db.session.add(faturado)
            db.session.flush()
        
        # Criar conta a pagar
        conta_pagar = ContaPagar(
            numero_nota_fiscal=data.get('numero_nota_fiscal'),
            data_emissao=datetime.strptime(data.get('data_emissao'), '%Y-%m-%d').date(),
            descricao_produtos=data.get('descricao_produtos'),
            valor_total=Decimal(str(data.get('valor_total'))),
            fornecedor_id=fornecedor.id,
            faturado_id=faturado.id
        )
        db.session.add(conta_pagar)
        db.session.flush()
        
        # Criar parcela
        parcela = ParcelaPagar(
            numero_parcela=1,
            data_vencimento=datetime.strptime(data.get('data_vencimento'), '%Y-%m-%d').date(),
            valor=Decimal(str(data.get('valor_total'))),
            conta_pagar_id=conta_pagar.id
        )
        db.session.add(parcela)
        
        # Criar ou buscar tipo de despesa
        classificacao_nome = data.get('classificacao_despesa')
        if classificacao_nome:
            tipo_despesa = TipoDespesa.query.filter_by(nome=classificacao_nome).first()
            
            if not tipo_despesa:
                tipo_despesa = TipoDespesa(
                    nome=classificacao_nome,
                    descricao=f"Categoria: {classificacao_nome}"
                )
                db.session.add(tipo_despesa)
                db.session.flush()
            
            # Criar classificação
            classificacao = ClassificacaoDespesa(
                conta_pagar_id=conta_pagar.id,
                tipo_despesa_id=tipo_despesa.id
            )
            db.session.add(classificacao)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Nota fiscal salva com sucesso',
            'conta_pagar_id': conta_pagar.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erro ao salvar: {str(e)}'}), 500

@app.route('/api/expense-categories', methods=['GET'])
def get_expense_categories():
    """
    Endpoint para obter todas as categorias de despesas
    """
    try:
        categories = expense_classifier.get_all_categories()
        return jsonify(categories), 200
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar categorias: {str(e)}'}), 500

@app.route('/api/fornecedores', methods=['GET'])
def get_fornecedores():
    """
    Endpoint para listar fornecedores
    """
    try:
        fornecedores = Fornecedor.query.filter_by(is_active=True).all()
        result = []
        
        for fornecedor in fornecedores:
            result.append({
                'id': fornecedor.id,
                'razao_social': fornecedor.razao_social,
                'fantasia': fornecedor.fantasia,
                'cnpj': fornecedor.cnpj,
                'created_at': fornecedor.created_at.isoformat()
            })
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar fornecedores: {str(e)}'}), 500

@app.route('/api/contas-pagar', methods=['GET'])
def get_contas_pagar():
    """
    Endpoint para listar contas a pagar
    """
    try:
        contas = ContaPagar.query.filter_by(is_active=True).all()
        result = []
        
        for conta in contas:
            result.append({
                'id': conta.id,
                'numero_nota_fiscal': conta.numero_nota_fiscal,
                'data_emissao': conta.data_emissao.isoformat(),
                'valor_total': float(conta.valor_total),
                'fornecedor': {
                    'razao_social': conta.fornecedor.razao_social,
                    'cnpj': conta.fornecedor.cnpj
                },
                'faturado': {
                    'nome_completo': conta.faturado.nome_completo,
                    'cpf': conta.faturado.cpf
                }
            })
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar contas: {str(e)}'}), 500

@app.route('/api/analyze-and-save', methods=['POST'])
def analyze_and_save():
    """
    Analisa a existência de FORNECEDOR, FATURADO e DESPESA e,
    após exibir a mensagem no frontend, cria os registros que faltam
    e lança a conta a pagar com parcela e classificação.
    Espera payload JSON no formato:
    {
      "fornecedor": {"razao_social": str, "fantasia": str, "cnpj": str},
      "faturado": {"nome_completo": str, "cpf": str},
      "classificacao_despesa": str,
      "numero_nota_fiscal": str,
      "data_emissao": "YYYY-MM-DD",
      "descricao_produtos": str,
      "valor_total": number,
      "data_vencimento": "YYYY-MM-DD"
    }
    """
    try:
        data = request.get_json() or {}

        # ===== Verificações =====
        fornecedor_data = data.get('fornecedor', {})
        faturado_data = data.get('faturado', {})
        classificacao_nome = data.get('classificacao_despesa')
        classificacoes = data.get('classificacoes') or []

        fornecedor = None
        faturado = None
        tipo_despesa = None

        if fornecedor_data.get('cnpj'):
            fornecedor = Fornecedor.query.filter_by(cnpj=fornecedor_data.get('cnpj')).first()
        if faturado_data.get('cpf'):
            faturado = Faturado.query.filter_by(cpf=faturado_data.get('cpf')).first()
        if classificacao_nome:
            tipo_despesa = TipoDespesa.query.filter_by(nome=classificacao_nome).first()

        def status_line(exists, id_value):
            return ("EXISTE – ID: " + str(id_value)) if exists else "NÃO EXISTE"

        # Montar mensagem de análise
        message_lines = [
            "FORNECEDOR:",
            str(fornecedor_data.get('razao_social') or ''),
            f"CNPJ: {fornecedor_data.get('cnpj') or ''}",
            status_line(bool(fornecedor), getattr(fornecedor, 'id', None)),
            "FATURADO",
            str(faturado_data.get('nome_completo') or ''),
            f"CPF: {faturado_data.get('cpf') or ''}",
            status_line(bool(faturado), getattr(faturado, 'id', None)),
            "DESPESA",
            str(classificacao_nome or ''),
            status_line(bool(tipo_despesa), getattr(tipo_despesa, 'id', None)),
        ]
        analysis_message = "\n".join(message_lines)

        # ===== Criações (se necessário) =====
        created = {"fornecedor": False, "faturado": False, "tipo_despesa": False}

        if not fornecedor:
            fornecedor = Fornecedor(
                razao_social=fornecedor_data.get('razao_social'),
                fantasia=fornecedor_data.get('fantasia'),
                cnpj=fornecedor_data.get('cnpj')
            )
            db.session.add(fornecedor)
            db.session.flush()
            created["fornecedor"] = True

        if not faturado:
            faturado = Faturado(
                nome_completo=faturado_data.get('nome_completo'),
                cpf=faturado_data.get('cpf')
            )
            db.session.add(faturado)
            db.session.flush()
            created["faturado"] = True

        if not tipo_despesa and classificacao_nome:
            tipo_despesa = TipoDespesa(
                nome=classificacao_nome,
                descricao=f"Categoria: {classificacao_nome}"
            )
            db.session.add(tipo_despesa)
            db.session.flush()
            created["tipo_despesa"] = True

        # ===== Lançar movimento (ContaPagar + Parcela + Classificação) =====
        conta_pagar = ContaPagar(
            numero_nota_fiscal=data.get('numero_nota_fiscal'),
            data_emissao=datetime.strptime(data.get('data_emissao'), '%Y-%m-%d').date(),
            descricao_produtos=data.get('descricao_produtos'),
            valor_total=Decimal(str(data.get('valor_total'))),
            fornecedor_id=fornecedor.id,
            faturado_id=faturado.id
        )
        db.session.add(conta_pagar)
        db.session.flush()

        parcela = ParcelaPagar(
            numero_parcela=1,
            data_vencimento=datetime.strptime(data.get('data_vencimento'), '%Y-%m-%d').date(),
            valor=Decimal(str(data.get('valor_total'))),
            conta_pagar_id=conta_pagar.id
        )
        db.session.add(parcela)

        if tipo_despesa:
            # Se houver lista de classificações, criar todas; caso contrário, apenas a única
            if classificacoes:
                for nome in classificacoes:
                    td = TipoDespesa.query.filter_by(nome=nome).first()
                    if not td:
                        td = TipoDespesa(nome=nome, descricao=f"Categoria: {nome}")
                        db.session.add(td)
                        db.session.flush()
                    classificacao = ClassificacaoDespesa(
                        conta_pagar_id=conta_pagar.id,
                        tipo_despesa_id=td.id
                    )
                    db.session.add(classificacao)
            else:
                classificacao = ClassificacaoDespesa(
                    conta_pagar_id=conta_pagar.id,
                    tipo_despesa_id=tipo_despesa.id
                )
                db.session.add(classificacao)

        db.session.commit()

        return jsonify({
            'success': True,
            'analysis_message': analysis_message,
            'created': {
                'fornecedor': created['fornecedor'],
                'faturado': created['faturado'],
                'tipo_despesa': created['tipo_despesa']
            },
            'ids': {
                'fornecedor_id': fornecedor.id,
                'faturado_id': faturado.id,
                'tipo_despesa_id': getattr(tipo_despesa, 'id', None),
                'conta_pagar_id': conta_pagar.id
            },
            'message': 'Registro foi lançado com sucesso.'
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erro ao analisar/salvar: {str(e)}'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Endpoint para verificar se a API está funcionando
    """
    return jsonify({
        'status': 'OK',
        'message': 'API funcionando corretamente',
        'timestamp': datetime.now().isoformat()
    }), 200