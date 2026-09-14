import { useEffect, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const TRANSFORMATION_GROUPS = [
  {
    label: "Protocolo est?ndar",
    options: [
      ["format_change", "T1 - Cambio de formato"],
      ["binary_recode", "T2 - Recodificaci?n binaria"],
      ["whitespace", "T3 - Espaciado / saltos"],
      ["ocr_reocr", "T4 - OCR / re-OCR"],
      ["case_punct", "T5 - May?sculas / puntuaci?n"],
      ["drop_fields", "T6 - Eliminaci?n de campos"],
      ["reorder_blocks", "T7 - Reordenamiento de bloques"],
      ["mask_pii", "T8 - Enmascaramiento PII"],
      ["combo_format_noise", "M1 - Formato + ruido"],
      ["combo_ocr_noise", "M2 - OCR + ruido"],
      ["combo_ocr_mask", "M3 - OCR + PII"],
      ["combo_reorder_mask", "M4 - Reordenamiento + PII"],
      ["combo_noise_drop", "M5 - Ruido + eliminaci?n"],
      ["combo_reorder_noise", "M6 - Reordenamiento + ruido"],
      ["combo_drop_case", "M7 - Eliminaci?n + puntuaci?n"],
      ["combo_noise_reorder_mask", "M8 - Ruido + reordenamiento + PII"],
      ["combo_drop_reorder_mask", "M9 - Eliminaci?n + reordenamiento + PII"],
      ["combo_strong", "M10 - Combinada fuerte"],
    ],
  },
  {
    label: "Visual enriquecido",
    options: [
      ["visual_redacted", "V1 - Redacci?n visual"],
      ["visual_redacted_reorder", "V2 - Redacci?n + reordenamiento"],
      ["visual_noise_redacted", "V3 - Ruido + redacci?n"],
      ["visual_strong", "V4 - Visual fuerte"],
    ],
  },
  {
    label: "Escaneo / OCR degradado",
    options: [
      ["scan_low_dpi", "S1 - Bajo DPI"],
      ["scan_low_dpi_blur", "S2 - Bajo DPI + blur"],
      ["scan_redacted_low_dpi", "S3 - Redactado + bajo DPI"],
      ["scan_strong_low_dpi", "S4 - Escaneo fuerte"],
    ],
  },
];

function App() {
  const [activeSection, setActiveSection] = useState("forensic");

  const [references, setReferences] = useState([]);
  const [referenceTotal, setReferenceTotal] = useState(0);

  const [referenceFiles, setReferenceFiles] = useState([]);
  const [suspiciousFile, setSuspiciousFile] = useState(null);
  const [matchResult, setMatchResult] = useState(null);

  const [corpusSize, setCorpusSize] = useState(50);
  const [evaluationResult, setEvaluationResult] = useState(null);

  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState(null);

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [selectedReferenceId, setSelectedReferenceId] = useState("");
  const [selectedTransformation, setSelectedTransformation] = useState("combined");
  const [variantMatchResult, setVariantMatchResult] = useState(null);

  async function fetchReferences() {
    try {
      const response = await fetch(`${API_BASE_URL}/references`);
      const data = await response.json();

      setReferences(data.documents || []);
      setReferenceTotal(data.total || 0);
    } catch {
      setMessage("Error al listar documentos de referencia.");
    }
  }
  async function fetchAnalysisHistory() {
  try {
    const response = await fetch(`${API_BASE_URL}/analysis/history`);
    const data = await response.json();

    setAnalysisHistory(data.items || []);
    setHistoryTotal(data.total || 0);
  } catch {
    setMessage("Error al listar historial de análisis.");
  }
}
async function generateVariantAndMatch() {
  if (!selectedReferenceId) {
    setMessage("Selecciona un documento legítimo primero.");
    return;
  }

  setLoading(true);
  setMessage("");
  setVariantMatchResult(null);

  try {
    const response = await fetch(
      `${API_BASE_URL}/references/${selectedReferenceId}/variant-and-match?transformation_type=${selectedTransformation}&top_k=5`,
      {
        method: "POST",
      }
    );

    const data = await response.json();

    if (!response.ok || data.error) {
      setMessage(data.error || "Error al generar variante y comparar.");
      return;
    }

    setVariantMatchResult(data);
    setMessage("Variante sospechosa generada y comparada correctamente.");
  } catch (error) {
    setMessage(`Error al generar variante y comparar: ${error.message}`);
  } finally {
    setLoading(false);
  }
}
  async function clearAnalysisHistory() {
    setLoading(true);
    setMessage("");

    try {
        const response = await fetch(`${API_BASE_URL}/analysis/history`, {
          method: "DELETE",
        });

        const data = await response.json();

        setMessage(`Historial limpiado. Registros eliminados: ${data.deleted}`);
        await fetchAnalysisHistory();
      } catch {
        setMessage("Error al limpiar historial.");
      } finally {
        setLoading(false);
      }
    }
    useEffect(() => {
      fetchReferences();
    }, []);
  async function fetchAnalysisHistory() {
    try {
      const response = await fetch(`${API_BASE_URL}/analysis/history`);
      const data = await response.json();

      setAnalysisHistory(data.items || []);
      setHistoryTotal(data.total || 0);
    } catch {
      setMessage("Error al listar historial de análisis.");
    }
  }

  async function clearAnalysisHistory() {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/analysis/history`, {
        method: "DELETE",
      });

      const data = await response.json();

      setMessage(`Historial limpiado. Registros eliminados: ${data.deleted}`);
      setAnalysisHistory([]);
      setHistoryTotal(0);
      setSelectedHistoryItem(null);
    } catch {
      setMessage("Error al limpiar historial.");
    } finally {
      setLoading(false);
    }
  }
  async function loadReferencesFromDb() {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/references/load-from-db`, {
        method: "POST",
      });

      const data = await response.json();
      setMessage(`Índice recargado desde SQLite. Total: ${data.total}`);
      await fetchReferences();
    } catch {
      setMessage("Error al recargar índice desde SQLite.");
    } finally {
      setLoading(false);
    }
  }

  async function clearReferences() {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/references`, {
        method: "DELETE",
      });

      const data = await response.json();
      setMessage(`Referencias eliminadas. SQLite: ${data.deleted_from_db}`);
      setReferences([]);
      setReferenceTotal(0);
      setMatchResult(null);
    } catch {
      setMessage("Error al limpiar referencias.");
    } finally {
      setLoading(false);
    }
  }
  async function uploadReferenceDocuments() {
    if (!referenceFiles.length) {
      setMessage("Selecciona uno o más documentos legítimos primero.");
      return;
    }

    setLoading(true);
    setMessage("");

    let successCount = 0;
    let failCount = 0;

    try {
      for (const file of referenceFiles) {
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(`${API_BASE_URL}/references/upload`, {
          method: "POST",
          body: formData,
        });

      if (response.ok) {
        successCount += 1;
      } else {
        failCount += 1;

        try {
          const errorData = await response.json();
          console.warn(`Error al cargar ${file.name}:`, errorData.detail || errorData.error);
        } catch {
          console.warn(`Error al cargar ${file.name}`);
        }
      }
      }

      setMessage(
        `Carga finalizada. Documentos legítimos cargados: ${successCount}. Rechazados o con error: ${failCount}.`
      );

      setReferenceFiles([]);
      await fetchReferences();
    } catch (error) {
      setMessage(`Error al subir documentos legítimos: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }
  async function generateSyntheticCorpus() {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(
        `${API_BASE_URL}/references/bootstrap-synthetic?n=${corpusSize}&clear_existing=true`,
        { method: "POST" }
      );

      const data = await response.json();
      setMessage(`Corpus sintético generado: ${data.added_to_reference_index} documentos.`);
      await fetchReferences();
    } catch {
      setMessage("Error al generar/cargar corpus sintético.");
    } finally {
      setLoading(false);
    }
  }

  async function matchSuspiciousDocument() {
    if (!suspiciousFile) {
      setMessage("Selecciona un documento sospechoso primero.");
      return;
    }

    setLoading(true);
    setMessage("");
    setMatchResult(null);

    try {
      const formData = new FormData();
      formData.append("file", suspiciousFile);

      const response = await fetch(`${API_BASE_URL}/documents/match?top_k=5`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      setMatchResult(data);
      setMessage("Documento sospechoso comparado correctamente.");
    } catch {
      setMessage("Error al comparar documento sospechoso.");
    } finally {
      setLoading(false);
    }
  }

  async function runEvaluationSummary() {
    setLoading(true);
    setMessage("");
    setEvaluationResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/evaluation/summary`, {
        method: "POST",
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        setMessage(data.error || "Error al ejecutar evaluación experimental.");
        setEvaluationResult(data);
        return;
      }

      setEvaluationResult(data);
      setMessage("Evaluación experimental ejecutada.");
    } catch (error) {
      setMessage(`Error al ejecutar evaluación experimental: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function saveEvaluationSummary() {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/evaluation/save-summary`, {
        method: "POST",
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        setMessage(data.error || "Error al guardar resumen experimental.");
        return;
      }

      setMessage(`Resumen guardado: ${data.filename || "archivo JSON generado"}`);
    } catch (error) {
      setMessage(`Error al guardar resumen experimental: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">FQ</div>
          <div>
            <h1>ForensiQ</h1>
            <span>Sandbox Forense</span>
          </div>
        </div>

        <nav className="side-nav">
          <span className="nav-label">Principal</span>
          <button
            className={activeSection === "forensic" ? "active" : ""}
            onClick={() => setActiveSection("forensic")}
          >
            <span>◉</span> Análisis forense
          </button>
          <button
            className={activeSection === "evaluation" ? "active" : ""}
            onClick={() => setActiveSection("evaluation")}
          >
            <span>▣</span> Evaluación experimental
          </button>
          <button
            className={activeSection === "history" ? "active" : ""}
            onClick={() => {
              setActiveSection("history");
              fetchAnalysisHistory();
            }}
          >
            <span>▦</span> Historial
          </button>

          <span className="nav-label">Datos</span>
          <button onClick={fetchReferences}>
            <span>↻</span> Actualizar índice
          </button>
          <button onClick={loadReferencesFromDb}>
            <span>▤</span> Recargar SQLite
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="avatar">AD</div>
          <div>
            <strong>Admin Usuario</strong>
            <span>Analista de seguridad</span>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>
                {activeSection === "forensic"
                  ? "Visor de Análisis Forense"
                  : activeSection === "evaluation"
                  ? "Laboratorio Experimental"
                  : "Historial de Archivos Analizados"}
            </h2>
            <p>
              {activeSection === "forensic"
                ? "Matching documental mediante huella multimodal"
                : activeSection === "evaluation"
                ? "Validación con corpus sintético, variantes y baselines"
                : "Registro persistente de documentos sospechosos procesados"}
            </p>
          </div>

          <div className="system-pills">
            <span className="pill good">Backend activo</span>
            <span className="pill good">SQLite conectado</span>
            <span className="pill alert">SBERT integrado</span>
            <span className="pill">Índice: {referenceTotal} refs</span>
          </div>
        </header>

        {message && <div className="notice">{message}</div>}
        {loading && <div className="loading">Procesando operación...</div>}

        {activeSection === "forensic" && (
          <main className="forensic-layout">
            <section className="panel large-panel">
              <PanelHeader
                title="Índice de documentos legítimos"
                badge={`${referenceTotal} cargados`}
              />

              <p className="muted">
                Documentos de referencia cargados en memoria y persistidos en SQLite.
              </p>
              <div className="upload-box reference-upload">
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
                  onChange={(event) => setReferenceFiles(Array.from(event.target.files || []))}
                />

                <span>
                  {referenceFiles.length
                    ? `${referenceFiles.length} documento(s) seleccionado(s)`
                    : "Selecciona uno o más documentos legítimos para agregarlos al índice"}
                </span>
                <p className="input-warning">
                  Solo carga documentos legítimos de referencia. No cargues archivos VARIANT_ ni documentos sospechosos en este índice.
                </p>
                {referenceFiles.length > 0 && (
                  <div className="selected-files">
                    {referenceFiles.slice(0, 5).map((file) => (
                      <span key={file.name}>{file.name}</span>
                    ))}

                    {referenceFiles.length > 5 && (
                      <span>+ {referenceFiles.length - 5} archivo(s) más</span>
                    )}
                  </div>
                )}

                <button className="primary full" onClick={uploadReferenceDocuments}>
                  Cargar documento(s) legítimo(s)
                </button>
              </div>
              <div className="toolbar">
                <button onClick={fetchReferences}>Actualizar</button>
                <button onClick={loadReferencesFromDb}>Recargar desde SQLite</button>
                <button className="danger" onClick={clearReferences}>
                  Limpiar índice
                </button>
              </div>

              <ReferenceTable references={references} />
            </section>

            <section className="panel">
              <PanelHeader title="Nuevo documento sospechoso" badge="Top-5" />

            <p className="muted">
              Carga una evidencia sospechosa para compararla contra el índice de documentos legítimos mediante huella multimodal.
            </p>

              <div className="upload-box">
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
                  onChange={(event) => setSuspiciousFile(event.target.files[0])}
                />
                <span>{suspiciousFile ? suspiciousFile.name : "Sin archivo seleccionado"}</span>
              </div>

              <button className="primary full" onClick={matchSuspiciousDocument}>
                Ejecutar matching forense
              </button>
              {matchResult && <EvidencePanel result={matchResult} />}
            </section>
            <section className="panel">
              <PanelHeader title="Simulación controlada" badge="Ground truth" />

              <p className="muted">
                Genera una variante alterada desde un documento legítimo conocido y verifica si el sistema recupera el documento original en el ranking.
              </p>

              <label className="field">
                Documento legítimo base
                <select
                  value={selectedReferenceId}
                  onChange={(event) => setSelectedReferenceId(event.target.value)}
                >
                  <option value="">Selecciona un documento</option>
                  {references.map((doc) => (
                    <option key={doc.document_id} value={doc.document_id}>
                      {doc.filename}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                Transformación
                <select
                  value={selectedTransformation}
                  onChange={(event) => setSelectedTransformation(event.target.value)}
                >
                  {TRANSFORMATION_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.options.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>

              <button className="primary full" onClick={generateVariantAndMatch}>
                Generar variante y comparar
              </button>

              {variantMatchResult && (
                <ControlledTestResult result={variantMatchResult} />
              )}
            </section>
            <section className="panel wide-panel">
              <PanelHeader title="Pipeline activo del prototipo" badge="MVP local" />

              <p className="muted">
                Flujo implementado para procesar documentos sensibles en entorno local,
                construir huellas multimodales y generar un ranking forense explicable.
              </p>

              <PipelineStatus />
            </section>
            {matchResult && (
              <section className="panel wide-panel">
                <PanelHeader title="Ranking de coincidencias" badge="Resultados" />
                <MatchResults result={matchResult} />
              </section>
            )}
          </main>
        )}

        {activeSection === "evaluation" && (
          <main className="evaluation-layout">
            <section className="panel">
              <PanelHeader title="Corpus sintético" badge="Generador" />

              <p className="muted">
                Genera documentos financieros sintéticos y cárgalos como referencias.
              </p>

              <label className="field">
                Cantidad de documentos
                <input
                  type="number"
                  min="1"
                  max="200"
                  value={corpusSize}
                  onChange={(event) => setCorpusSize(event.target.value)}
                />
              </label>

              <button className="primary full" onClick={generateSyntheticCorpus}>
                Generar y cargar corpus
              </button>
            </section>

            <section className="panel">
              <PanelHeader title="Evaluación experimental" badge="Métricas" />

              <p className="muted">
                Ejecuta baselines, ablaciones y métodos multimodales sobre las variantes.
              </p>

              <div className="toolbar vertical">
                <button onClick={runEvaluationSummary}>Ejecutar evaluación</button>
                <button onClick={saveEvaluationSummary}>Guardar JSON</button>
              </div>
            </section>

            {evaluationResult && (
              <section className="panel full-panel">
                <PanelHeader title="Resumen experimental" badge="Recall / MRR / AUC" />
                <EvaluationTable result={evaluationResult} />
              </section>
            )}
          </main>
        )}
        {activeSection === "history" && (
          <main className="history-layout">
            <section className="panel full-panel">
              <PanelHeader
                title="Historial de archivos analizados"
                badge={`${historyTotal} registros`}
              />

              <p className="muted">
                Registro persistente de documentos sospechosos procesados mediante matching forense.
              </p>

              <div className="toolbar">
                <button onClick={fetchAnalysisHistory}>Actualizar historial</button>
                <button className="danger" onClick={clearAnalysisHistory}>
                  Limpiar historial
                </button>
              </div>

              <HistoryTable
                items={analysisHistory}
                onSelectItem={setSelectedHistoryItem}
              />
            </section>

            {selectedHistoryItem && (
              <section className="panel full-panel">
                <PanelHeader
                  title="Detalle del análisis"
                  badge={`Caso #${selectedHistoryItem.id}`}
                />

                <HistoryDetail item={selectedHistoryItem} />
              </section>
            )}
          </main>
        )}
      </section>
    </div>
  );
}

function PanelHeader({ title, badge }) {
  return (
    <div className="panel-header">
      <h3>{title}</h3>
      {badge && <span>{badge}</span>}
    </div>
  );
}
function PipelineStatus() {
  const steps = [
    {
      title: "Extracción textual",
      description: "PDF con texto embebido y OCR local para documentos reprocesados.",
      status: "Activo",
    },
    {
      title: "Detección PII",
      description: "Reglas para identificar entidades sensibles sintéticas.",
      status: "Activo",
    },
    {
      title: "Layout documental",
      description: "Extracción de bloques y características estructurales básicas.",
      status: "Activo",
    },
    {
      title: "SBERT 384d",
      description: "Descriptor semántico liviano para comparación textual.",
      status: "Experimental",
    },
    {
      title: "Huella multimodal",
      description: "Fusión de texto, layout y PII mediante score ponderado.",
      status: "Principal",
    },
    {
      title: "Historial",
      description: "Registro persistente de análisis y Top-5 candidatos.",
      status: "Activo",
    },
  ];

  return (
    <div className="pipeline-grid">
      {steps.map((step) => (
        <div className="pipeline-card" key={step.title}>
          <div className="pipeline-card-header">
            <strong>{step.title}</strong>
            <span>{step.status}</span>
          </div>
          <p>{step.description}</p>
        </div>
      ))}
    </div>
  );
}
function ReferenceTable({ references }) {
  if (!references.length) {
    return <div className="empty-state">No hay documentos cargados en el índice.</div>;
  }

  return (
    <div className="table-wrap compact">
      <table>
        <thead>
          <tr>
            <th>Documento</th>
            <th>Texto</th>
            <th>PII</th>
            <th>Huella</th>
          </tr>
        </thead>
        <tbody>
          {references.map((doc) => (
            <tr key={doc.document_id}>
              <td className="doc-name" title={doc.filename}>
                {doc.filename}
              </td>
              <td>{doc.text_length}</td>
              <td>
                <span className="tag red">{doc.pii_count}</span>
              </td>
              <td>
                {doc.fingerprint_summary?.semantic_embedding_dimensions
                  ? "Multimodal + SBERT"
                  : "Multimodal"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function VisualSummaryCard({ summary }) {
  if (!summary) return null;

  return (
    <div className="visual-summary-card">
      <div className="visual-summary-title">
        <strong>Se?ales layout / visuales</strong>
        <span>{summary.visual_condition || "Resumen visual no disponible"}</span>
      </div>

      <div className="visual-summary-grid">
        <div>
          <span>Bloques texto</span>
          <strong>{summary.text_block_count ?? 0}</strong>
        </div>
        <div>
          <span>Gr?ficos</span>
          <strong>{summary.graphic_block_count ?? 0}</strong>
        </div>
        <div>
          <span>Im?genes</span>
          <strong>{summary.image_block_count ?? 0}</strong>
        </div>
        <div>
          <span>Visual/texto</span>
          <strong>{formatScore(summary.visual_to_text_ratio)}</strong>
        </div>
      </div>
    </div>
  );
}

function SignalBadge({ explanation }) {
  if (!explanation) return <span className="signal-badge neutral">?</span>;

  const signal = explanation.dominant_signal || "neutral";
  const labelMap = {
    texto: "Texto",
    pii: "PII",
    layout_visual: "Layout visual",
  };

  return (
    <span className={`signal-badge ${signal}`}>
      {labelMap[signal] || signal}
    </span>
  );
}

function MatchExplanation({ explanation }) {
  if (!explanation) return <span className="muted">?</span>;

  return (
    <span className="match-explanation" title={explanation.explanation}>
      {shortText(explanation.explanation, 52)}
    </span>
  );
}

function EvidencePanel({ result }) {
  const best = result.matches?.[0];

  return (
    <div className="evidence-panel">
      <h4>Resumen del análisis</h4>

      <div className="evidence-row">
        <span>Archivo</span>
        <strong>{result.filename}</strong>
      </div>

      <div className="evidence-row">
        <span>PII detectada</span>
        <strong>{result.pii_count}</strong>
      </div>
      <div className="evidence-row">
        <span>Entidades NLP</span>
        <strong>{result.nlp_entity_count ?? 0}</strong>
      </div>

      <div className="evidence-row">
        <span>Modo de extracción</span>
        <strong>{formatExtractionMode(result.extraction_mode)}</strong>
      </div>

      <div className="evidence-row">
        <span>OCR usado</span>
        <strong className={result.ocr_used ? "hit-text" : ""}>
          {result.ocr_used ? "Sí" : "No"}
        </strong>
      </div>
      <div className="evidence-row">
        <span>Bloques layout</span>
        <strong>{result.layout_block_count ?? "—"}</strong>
      </div>

      <VisualSummaryCard summary={result.visual_summary} />

      <div className="evidence-row">
        <span>Longitud texto</span>
        <strong>{result.text_length ?? 0} caracteres</strong>
      </div>
      <div className="evidence-row">
        <span>Mejor candidato</span>
        <strong>{best?.filename || "—"}</strong>
      </div>

      <div className="score-card">
        <span>Score final</span>
        <strong>{formatScore(best?.scores?.final_score)}</strong>
      </div>
      <button
        className="primary full"
        onClick={() =>
          downloadJson(
            result,
            `forensiq_analysis_${safeFilename(result.filename)}.json`
          )
        }
      >
        Exportar análisis JSON
      </button>

      {best && (
        <div className="score-bars">
          <ScoreBar label="Texto" value={best.scores?.text_score} />
          <ScoreBar label="SBERT" value={best.scores?.semantic_text_score} />
          <ScoreBar label="Layout" value={best.scores?.layout_score} />
          <ScoreBar label="PII" value={best.scores?.pii_score} />
        </div>
      )}
      {result.nlp_entities?.length > 0 && (
        <EntityPreview
          title="Entidades NLP detectadas"
          entities={result.nlp_entities}
        />
      )}
      <div className="evidence-row">
        <span>Bloques layout</span>
        <strong>{result.layout_block_count ?? "—"}</strong>
      </div>

      <div className="evidence-row">
        <span>Longitud texto</span>
        <strong>{result.text_length ?? 0} caracteres</strong>
      </div>
    </div>
  );
}
function EntityPreview({ title, entities }) {
  const visibleEntities = (entities || []).slice(0, 10);

  return (
    <div className="entity-preview">
      <h4>{title}</h4>

      <div className="entity-chips">
        {visibleEntities.map((entity, index) => {
          const type = entity.type || entity.label || entity.entity_type || "ENTITY";
          const value = entity.value || entity.text || entity.masked_value || "—";

          return (
            <span className="entity-chip" key={`${type}-${value}-${index}`}>
              <strong>{type}</strong>
              {shortText(value, 28)}
            </span>
          );
        })}
      </div>

      {entities && entities.length > visibleEntities.length && (
        <p className="muted small-muted">
          + {entities.length - visibleEntities.length} entidades adicionales.
        </p>
      )}
    </div>
  );
}
function TextPreview({ text }) {
  return (
    <div className="text-preview">
      <h4>Texto extraído</h4>
      <pre>{text}</pre>
    </div>
  );
}
function MatchResults({ result }) {
  return (
    <div className="results-block">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pos.</th>
              <th>Documento candidato</th>
              <th>Score final</th>
              <th>Texto</th>
              <th>SBERT</th>
              <th>Layout</th>
              <th>PII</th>
              <th>Se?al</th>
              <th>Explicaci?n</th>
            </tr>
          </thead>
          <tbody>
            {(result.matches || []).map((match, index) => (
              <tr key={match.document_id}>
                <td>{index + 1}</td>
                <td className="doc-name" title={match.filename}>
                  {match.filename}
                </td>
                <td>
                  <span className="score-highlight">
                    {formatScore(match.scores?.final_score)}
                  </span>
                </td>
                <td>{formatScore(match.scores?.text_score)}</td>
                <td>{formatScore(match.scores?.semantic_text_score)}</td>
                <td>{formatScore(match.scores?.layout_score)}</td>
                <td>{formatScore(match.scores?.pii_score)}</td>
                <td>
                  <SignalBadge explanation={match.analyst_explanation} />
                </td>
                <td>
                  <MatchExplanation explanation={match.analyst_explanation} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function ControlledTestResult({ result }) {
  return (
    <div className="controlled-result">
      <h4>Resultado de prueba controlada</h4>
      <VisualSummaryCard summary={result.visual_summary} />

      <div className="controlled-grid">
        <div>
          <span>Documento original</span>
          <strong title={result.source_filename}>
            {shortText(result.source_filename, 34)}
          </strong>
        </div>

        <div>
          <span>Transformación</span>
          <strong>{result.transformation_type}</strong>
        </div>

        <div>
          <span>Posición del verdadero</span>
          <strong>{result.rank_position ?? "No encontrado"}</strong>
        </div>

        <div>
          <span>Recall@1</span>
          <strong className={result.top_1_hit ? "hit-text" : "miss-text"}>
            {result.top_1_hit ? "Acierto" : "Fallo"}
          </strong>
        </div>

        <div>
          <span>Recall@5</span>
          <strong className={result.top_5_hit ? "hit-text" : "miss-text"}>
            {result.top_5_hit ? "Acierto" : "Fallo"}
          </strong>
        </div>

        <div>
          <span>PII detectada</span>
          <strong>{result.pii_count}</strong>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pos.</th>
              <th>Candidato</th>
              <th>Score final</th>
              <th>Texto</th>
              <th>SBERT</th>
              <th>Layout</th>
              <th>PII</th>
              <th>Se?al</th>
              <th>Explicaci?n</th>
            </tr>
          </thead>
          <tbody>
            {(result.matches || []).map((match, index) => (
              <tr key={`${match.document_id}-${index}`}>
                <td>{index + 1}</td>
                <td className="doc-name" title={match.filename}>
                  {match.filename}
                </td>
                <td>
                  <span className="score-highlight">
                    {formatScore(match.scores?.final_score)}
                  </span>
                </td>
                <td>{formatScore(match.scores?.text_score)}</td>
                <td>{formatScore(match.scores?.semantic_text_score)}</td>
                <td>{formatScore(match.scores?.layout_score)}</td>
                <td>{formatScore(match.scores?.pii_score)}</td>
                <td>
                  <SignalBadge explanation={match.analyst_explanation} />
                </td>
                <td>
                  <MatchExplanation explanation={match.analyst_explanation} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function EvaluationTable({ result }) {
  if (result.error) {
    return <div className="empty-state danger-text">{result.error}</div>;
  }

  const rows = result.summary || [];

  const bestRecall1 = getBestValue(rows, "recall_at_1", "max");
  const bestRecall5 = getBestValue(rows, "recall_at_5", "max");
  const bestMrr = getBestValue(rows, "mrr", "max");
  const bestAuc = getBestValue(rows, "auc_roc", "max");
  const bestFpr = getBestValue(rows, "fpr", "min");

  const bestOverall = getBestOverallMethod(rows);

  return (
    <div className="results-block">
      <div className="stats-grid">
        <div>
          <span>Documentos legítimos</span>
          <strong>{result.total_reference_documents}</strong>
        </div>
        <div>
          <span>Variantes generadas</span>
          <strong>{result.total_variants_generated}</strong>
        </div>
        <div>
          <span>Métodos evaluados</span>
          <strong>{rows.length}</strong>
        </div>
      </div>

      {bestOverall && (
        <div className="winner-card">
          <div>
            <span>Mejor método general</span>
            <strong>{bestOverall.method}</strong>
          </div>
          <div className="winner-metrics">
            <span>Recall@1: {formatScore(bestOverall.recall_at_1)}</span>
            <span>Recall@5: {formatScore(bestOverall.recall_at_5)}</span>
            <span>MRR: {formatScore(bestOverall.mrr)}</span>
          </div>
        </div>
      )}

      <div className="metric-legend">
        <span className="legend-item winner">Ganador general</span>
        <span className="legend-item best-high">Mayor es mejor</span>
        <span className="legend-item best-low">Menor es mejor</span>
        <span className="legend-item neutral">Latencia informativa</span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Método</th>
              <th>Recall@1</th>
              <th>Recall@5</th>
              <th>MRR</th>
              <th>FPR</th>
              <th>AUC-ROC</th>
              <th>Lat. prom.</th>
              <th>Lat. p95</th>
              <th>Casos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isOverallWinner = bestOverall?.method === row.method;

              return (
                <tr
                  key={row.method}
                  className={isOverallWinner ? "overall-winner-row" : ""}
                >
                  <td className="doc-name" title={row.method}>
                    {row.method}
                    {isOverallWinner && <span className="winner-badge">Mejor</span>}
                  </td>

                  <td className={metricClass(row.recall_at_1, bestRecall1, "high")}>
                    {formatScore(row.recall_at_1)}
                  </td>

                  <td className={metricClass(row.recall_at_5, bestRecall5, "high")}>
                    {formatScore(row.recall_at_5)}
                  </td>

                  <td className={metricClass(row.mrr, bestMrr, "high")}>
                    {formatScore(row.mrr)}
                  </td>

                  <td className={metricClass(row.fpr, bestFpr, "low")}>
                    {formatScore(row.fpr)}
                  </td>

                  <td className={metricClass(row.auc_roc, bestAuc, "high")}>
                    {formatScore(row.auc_roc)}
                  </td>

                  <td className="latency-cell">{row.avg_latency_ms ?? "—"}</td>
                  <td className="latency-cell">{row.p95_latency_ms ?? "—"}</td>
                  <td>{row.total_cases}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function HistoryTable({ items, onSelectItem }) {
  if (!items.length) {
    return <div className="empty-state">No hay análisis registrados.</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Archivo sospechoso</th>
            <th>Tipo</th>
            <th>Fecha</th>
            <th>PII</th>
            <th>Latencia</th>
            <th>Mejor candidato</th>
            <th>Score</th>
            <th>Detalle</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td className="doc-name" title={item.filename}>
                {item.filename}
              </td>
              <td>{item.file_type}</td>
              <td>{formatDate(item.created_at)}</td>
              <td>
                <span className="tag red">{item.pii_count}</span>
              </td>
              <td>{item.latency_ms ? `${item.latency_ms} ms` : "—"}</td>
              <td className="doc-name" title={item.best_match_filename || ""}>
                {item.best_match_filename || "—"}
              </td>
              <td>
                <span className="score-highlight">
                  {formatScore(item.best_match_score)}
                </span>
              </td>
              <td>
                <button className="small-button" onClick={() => onSelectItem(item)}>
                  Ver
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HistoryDetail({ item }) {
  const matches = item.matches || [];

  return (
    <div className="history-detail">
      <div className="stats-grid">
        <div>
          <span>Archivo sospechoso</span>
          <strong title={item.filename}>{shortText(item.filename, 34)}</strong>
        </div>
        <div>
          <span>Mejor candidato</span>
          <strong title={item.best_match_filename || ""}>
            {shortText(item.best_match_filename || "—", 34)}
          </strong>
        </div>
        <div>
          <span>Score final</span>
          <strong>{formatScore(item.best_match_score)}</strong>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pos.</th>
              <th>Documento candidato</th>
              <th>Score final</th>
              <th>Texto</th>
              <th>SBERT</th>
              <th>Layout</th>
              <th>PII</th>
              <th>Se?al</th>
              <th>Explicaci?n</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((match, index) => (
              <tr key={`${match.document_id}-${index}`}>
                <td>{index + 1}</td>
                <td className="doc-name" title={match.filename}>
                  {match.filename}
                </td>
                <td>
                  <span className="score-highlight">
                    {formatScore(match.scores?.final_score)}
                  </span>
                </td>
                <td>{formatScore(match.scores?.text_score)}</td>
                <td>{formatScore(match.scores?.semantic_text_score)}</td>
                <td>{formatScore(match.scores?.layout_score)}</td>
                <td>{formatScore(match.scores?.pii_score)}</td>
                <td>
                  <SignalBadge explanation={match.analyst_explanation} />
                </td>
                <td>
                  <MatchExplanation explanation={match.analyst_explanation} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function getNumericValue(value) {
  const number = Number(value);

  if (Number.isNaN(number) || !Number.isFinite(number)) {
    return null;
  }

  return number;
}

function getBestValue(rows, key, mode = "max") {
  const values = rows
    .map((row) => getNumericValue(row[key]))
    .filter((value) => value !== null);

  if (!values.length) return null;

  return mode === "min" ? Math.min(...values) : Math.max(...values);
}

function isSameMetricValue(value, bestValue) {
  const numericValue = getNumericValue(value);

  if (numericValue === null || bestValue === null) {
    return false;
  }

  return Math.abs(numericValue - bestValue) < 0.00001;
}

function metricClass(value, bestValue, direction) {
  if (!isSameMetricValue(value, bestValue)) {
    return "";
  }

  return direction === "low" ? "best-low-cell" : "best-high-cell";
}

function getBestOverallMethod(rows) {
  if (!rows.length) return null;

  const sortedRows = [...rows].sort((a, b) => {
    const recallA = getNumericValue(a.recall_at_1) ?? -1;
    const recallB = getNumericValue(b.recall_at_1) ?? -1;

    if (recallB !== recallA) {
      return recallB - recallA;
    }

    const mrrA = getNumericValue(a.mrr) ?? -1;
    const mrrB = getNumericValue(b.mrr) ?? -1;

    if (mrrB !== mrrA) {
      return mrrB - mrrA;
    }

    const fprA = getNumericValue(a.fpr) ?? 999;
    const fprB = getNumericValue(b.fpr) ?? 999;

    return fprA - fprB;
  });

  return sortedRows[0];
}
function ScoreBar({ label, value }) {
  const numericValue = Number(value || 0);
  const percentage = Math.max(0, Math.min(100, numericValue * 100));

  return (
    <div className="score-bar">
      <div>
        <span>{label}</span>
        <strong>{formatScore(value)}</strong>
      </div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }

  return Number(value).toFixed(4);
}
function downloadJson(data, filename = "forensiq_analysis.json") {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();

  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function safeFilename(value) {
  if (!value) return "analysis";
  return String(value)
    .replace(/[^a-zA-Z0-9._-]/g, "_")
    .slice(0, 80);
}
function shortText(value, maxLength = 40) {
  if (!value) return "—";
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength)}...`;
}
function formatExtractionMode(value) {
  if (!value) return "—";

  const labels = {
    direct_text: "Texto directo",
    ocr_fallback: "OCR fallback",
    direct_text_empty_or_low_quality: "Texto directo insuficiente",
  };

  return labels[value] || value;
}
function formatDate(value) {
  if (!value) return "—";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}



export default App;