import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5000';

function App() {
  const [file, setFile] = useState(null);
  const [extractedData, setExtractedData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const onDrop = (acceptedFiles) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setError('');
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf']
    },
    multiple: false
  });

  const extractData = async () => {
    if (!file) {
      setError('Por favor, selecione um arquivo PDF');
      return;
    }

    setLoading(true);
    setError('');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(`${API_BASE_URL}/api/upload-pdf`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      setExtractedData(response.data);
      setSuccess('Dados extraídos com sucesso!');
    } catch (err) {
      setError('Erro ao extrair dados: ' + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const saveToDatabase = async () => {
    if (!extractedData) {
      setError('Nenhum dado para salvar');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await axios.post(`${API_BASE_URL}/api/save-invoice`, extractedData);
      setSuccess('Dados salvos no banco de dados com sucesso!');
    } catch (err) {
      setError('Erro ao salvar dados: ' + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = () => {
    if (extractedData) {
      navigator.clipboard.writeText(JSON.stringify(extractedData, null, 2));
      setSuccess('JSON copiado para a área de transferência!');
    }
  };

  return (
    <div className="App">
      <div className="container">
        <div className="header">
          <h1>🧾 Extração de Dados de Nota Fiscal</h1>
          <p>Carregue um PDF da nota fiscal e extraia os dados automaticamente usando IA</p>
        </div>

        {/* Card de Upload */}
        <div className="card">
          <h3>📤 Upload de Arquivo</h3>
          <div {...getRootProps()} className={`upload-area ${isDragActive ? 'dragover' : ''}`}>
            <input {...getInputProps()} />
            {isDragActive ? (
              <div>
                <div className="upload-icon">📄</div>
                <p><strong>Solte o arquivo aqui...</strong></p>
              </div>
            ) : (
              <div>
                <div className="upload-icon">📄</div>
                <p><strong>Arraste e solte seu PDF aqui</strong></p>
                <p>ou clique para selecionar o arquivo</p>
                <div className="file-types">Aceita apenas arquivos PDF</div>
              </div>
            )}
          </div>

          {file && (
            <div className="file-info">
              <span className="file-icon">📄</span>
              <div className="file-details">
                <strong>{file.name}</strong>
                <div className="file-size">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
              </div>
              <button 
                onClick={() => setFile(null)} 
                className="btn btn-remove"
                title="Remover arquivo"
              >
                ✕
              </button>
            </div>
          )}

          <div className="button-group">
            <button 
              onClick={extractData} 
              disabled={loading || !file}
              className="btn btn-primary btn-large"
            >
              {loading ? (
                <>
                  <div className="spinner"></div>
                  Processando...
                </>
              ) : (
                <>
                  🔍 Extrair Dados
                </>
              )}
            </button>
          </div>
        </div>

        {/* Mensagens de Status */}
        {error && <div className="error">❌ {error}</div>}
        {success && <div className="success">✅ {success}</div>}

        {/* Card de Resultados */}
        {extractedData && (
          <div className="card">
            <h3>📊 Dados Extraídos</h3>
            
            <div className="button-group">
              <button onClick={copyToClipboard} className="btn btn-secondary">
                📋 Copiar JSON
              </button>
              <button 
                onClick={saveToDatabase}
                disabled={loading}
                className="btn btn-success"
              >
                {loading ? (
                  <>
                    <div className="spinner"></div>
                    Salvando...
                  </>
                ) : (
                  <>
                    💾 Salvar no Banco
                  </>
                )}
              </button>
            </div>

            <div className="json-container">
              <h4>📋 Dados em JSON</h4>
              <pre>{JSON.stringify(extractedData, null, 2)}</pre>
            </div>

            <div className="info-text">
              <p>💡 Este JSON contém todos os dados extraídos da nota fiscal e pode ser usado para integração com outros sistemas.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;