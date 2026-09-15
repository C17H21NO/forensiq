import { useState } from "react";
import "./App.css";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const ROLE_LABELS = {
  ADMIN: "Administrador",
  ANALYST: "Analista forense",
  DPO: "DPO / Revisor PII",
};


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
  const [auth, setAuth] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("forensiq_auth") || "null");
    } catch {
      return null;
    }
  });
  const [loginForm, setLoginForm] = useState({
    username: "",
    password: "",
  });
  const [loginError, setLoginError] = useState("");
  const currentUser = auth?.user || null;
  const token = auth?.access_token || "";

  const isAdmin = currentUser?.role === "ADMIN";
  const isAnalyst =
    currentUser?.role === "ANALYST" || currentUser?.role === "ADMIN";
  const isDpo = currentUser?.role === "DPO";

  const canRunTopK = isAnalyst;
  const canViewHistory = isAdmin || isDpo;

  const [activeSection, setActiveSection] = useState("home");

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

  async function handleLogin(event) {
    event.preventDefault();
    setLoginError("");
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });

      const data = await response.json();

      if (!response.ok) {
        setLoginError(data.detail || "No se pudo iniciar sesión.");
        return;
      }

      localStorage.setItem("forensiq_auth", JSON.stringify(data));
      setAuth(data);
      setMessage(`Sesión iniciada como ${ROLE_LABELS[data.user.role] || data.user.role}.`);
      setActiveSection("home");
    } catch (error) {
      setLoginError(`Error de conexión con el backend: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("forensiq_auth");
    setAuth(null);
    setReferences([]);
    setAnalysisHistory([]);
    setMatchResult(null);
    setEvaluationResult(null);
    setSelectedHistoryItem(null);
    setMessage("");
  }

  async function apiFetch(url, options = {}) {
    const headers = { ...(options.headers || {}) };

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      handleLogout();
      throw new Error("Sesión expirada. Inicia sesión nuevamente.");
    }

    if (response.status === 403) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "No tienes permisos para esta operación.");
    }

    return response;
  }

  async function fetchReferences() {
    try {
      const response = await apiFetch(`${API_BASE_URL}/references`);
      const data = await response.json();

      setReferences(data.documents || []);
      setReferenceTotal(data.total || 0);
    } catch {
      setMessage("Error al listar documentos de referencia.");
    }
  }
  async function fetchAnalysisHistory() {
  try {
    const response = await apiFetch(`${API_BASE_URL}/analysis/history`);
    const data = await response.json();

    setAnalysisHistory(data.items || []);
    setHistoryTotal(data.total || 0);
  } catch {
    setMessage("Error al listar historial de análisis.");
  }
  }
  function openForensicSection() {
    setActiveSection("forensic");
    setMessage("");
  }

  async function openReferencesSection() {
    setActiveSection("references");
    setMessage("");
    await fetchReferences();
  }

  async function openHistorySection() {
    setActiveSection("history");
    setMessage("");
    await fetchAnalysisHistory();
  }

  async function openEvaluationSection() {
    setActiveSection("evaluation");
    setMessage("");
    await fetchReferences();
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
    const response = await apiFetch(
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
  const confirmed = window.confirm(
    "¿Eliminar todo el historial de análisis?\n\nEsta acción eliminará los registros almacenados y no se puede deshacer."
  );

  if (!confirmed) {
    return;
  }

  setLoading(true);
  setMessage("");

  try {
    const response = await apiFetch(`${API_BASE_URL}/analysis/history`, {
      method: "DELETE",
    });

    const data = await response.json();

    if (!response.ok) {
      setMessage(
        data.detail ||
        data.error ||
        "No se pudo eliminar el historial."
      );
      return;
    }

    setAnalysisHistory([]);
    setHistoryTotal(0);
    setSelectedHistoryItem(null);

    setMessage(
      `Historial eliminado. Registros eliminados: ${data.deleted ?? 0}.`
    );
  } catch (error) {
    setMessage(
      `No se pudo eliminar el historial: ${error.message}`
    );
  } finally {
    setLoading(false);
  }
}
async function loadReferencesFromDb() {
  setLoading(true);
  setMessage("");

  try {
    const response = await apiFetch(
      `${API_BASE_URL}/references/load-from-db`,
      {
        method: "POST",
      }
    );

    const data = await response.json();

    if (!response.ok) {
      setMessage(
        data.detail ||
        data.error ||
        "No se pudo reconstruir el índice de referencias."
      );
      return;
    }

    setMessage(
      `Índice reconstruido correctamente. Referencias disponibles: ${data.total ?? 0}.`
    );

    await fetchReferences();
  } catch (error) {
    setMessage(
      `No se pudo reconstruir el índice de referencias: ${error.message}`
    );
  } finally {
    setLoading(false);
  }
}

async function clearReferences() {
  const confirmed = window.confirm(
    `¿Eliminar todas las referencias?\n\nActualmente hay ${referenceTotal} referencia(s) registradas. Esta acción afectará los próximos análisis y no se puede deshacer desde la aplicación.`
  );

  if (!confirmed) {
    return;
  }

  setLoading(true);
  setMessage("");

  try {
    const response = await apiFetch(`${API_BASE_URL}/references`, {
      method: "DELETE",
    });

    const data = await response.json();

    if (!response.ok) {
      setMessage(
        data.detail ||
        data.error ||
        "No se pudieron eliminar las referencias."
      );
      return;
    }

    setReferences([]);
    setReferenceTotal(0);
    setReferenceFiles([]);
    setSelectedReferenceId("");
    setVariantMatchResult(null);
    setMatchResult(null);

    setMessage(
      `Referencias eliminadas. Documentos eliminados: ${data.deleted_from_db ?? 0}.`
    );
  } catch (error) {
    setMessage(
      `No se pudieron eliminar las referencias: ${error.message}`
    );
  } finally {
    setLoading(false);
  }
}
  async function uploadReferenceDocuments() {
    if (!referenceFiles.length) {
      setMessage("Selecciona uno o más documentos de referencia.");
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

        const response = await apiFetch(`${API_BASE_URL}/references/upload`, {
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
        failCount === 0
          ? `Carga completada. ${successCount} documento(s) agregado(s) como referencia.`
          : `Carga completada. Agregados: ${successCount}. No procesados: ${failCount}.`
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
      const response = await apiFetch(
        `${API_BASE_URL}/references/bootstrap-synthetic?n=${corpusSize}&clear_existing=true&confirm_clear=DELETE_REFERENCE_CORPUS`,
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

      const response = await apiFetch(`${API_BASE_URL}/documents/match?top_k=5`, {
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
      const response = await apiFetch(`${API_BASE_URL}/evaluation/summary`, {
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
      const response = await apiFetch(`${API_BASE_URL}/evaluation/save-summary`, {
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

  if (!token || !currentUser) {
    return (
      <LoginScreen
        loginForm={loginForm}
        setLoginForm={setLoginForm}
        onSubmit={handleLogin}
        loading={loading}
        loginError={loginError}
      />
    );
  }

  return (
    <div className="app">
      <aside
  className="sidebar"
  aria-label="Navegación principal"
>
        <div className="brand">
          <div className="brand-icon">FQ</div>
          <div>
            <h1>ForensiQ</h1>
            <span>Sandbox Forense</span>
          </div>
        </div>

        <nav
  className="side-nav"
  aria-label="Secciones de ForensiQ"
>
          <span className="nav-label">Principal</span>

          <button
            className={activeSection === "home" ? "active" : ""}
            aria-current={activeSection === "home" ? "page" : undefined}
            onClick={() => setActiveSection("home")}
          >
            Inicio
          </button>

          {canRunTopK && (
            <button
  className={activeSection === "forensic" ? "active" : ""}
  aria-current={activeSection === "forensic" ? "page" : undefined}
  onClick={openForensicSection}
>
  Analizar documento
</button>
          )}
          {isAnalyst && (
            <button
              className={activeSection === "references" ? "active" : ""}
              onClick={openReferencesSection}
            >
              Referencias
            </button>
          )}
          {canViewHistory && (
            <button
              className={activeSection === "history" ? "active" : ""}
              onClick={openHistorySection}
            >
              Historial
            </button>
          )}

          {isAdmin && (
            <>
              <span className="nav-label">Administración</span>

              <button
                className={activeSection === "evaluation" ? "active" : ""}
                onClick={openEvaluationSection}
              >
                Experimental
              </button>
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div className="avatar">{currentUser.role?.slice(0, 2)}</div>
          <div>
            <strong>{currentUser.full_name}</strong>
            <span>{ROLE_LABELS[currentUser.role] || currentUser.role}</span>
          </div>
          <button className="logout-button" onClick={handleLogout}>Salir</button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>
              {activeSection === "home"
                ? "Inicio"
                : activeSection === "forensic"
                  ? "Analizar documento"
                  : activeSection === "references"
                    ? "Documentos de referencia"
                    : activeSection === "evaluation"
                      ? "Área experimental"
                      : "Historial de análisis"}
            </h2>

            <p>
              {activeSection === "home"
                ? "Revisión asistida de documentos sospechosos"
                : activeSection === "forensic"
                  ? "Compara un documento sospechoso con las referencias disponibles"
                  : activeSection === "references"
                    ? "Consulta los documentos legítimos utilizados como referencia"
                    : activeSection === "evaluation"
                      ? "Funciones reservadas para evaluación técnica y reproducibilidad"
                      : "Consulta los análisis registrados por el sistema"}
            </p>
          </div>

          <div className="system-pills">
            <span className="pill">
              {ROLE_LABELS[currentUser.role] || currentUser.role}
            </span>
          </div>
        </header>

        {message && (
  <div
    className="notice"
    role="status"
    aria-live="polite"
  >
    {message}
  </div>
)}

{loading && (
  <div
    className="loading"
    role="status"
    aria-live="polite"
  >
    Procesando operación...
  </div>
)}
        {activeSection === "home" && (
          <main className="history-layout">
            <section className="panel full-panel home-hero">
              <div className="home-hero-content">
                <span className="home-eyebrow">ForensiQ</span>

                <h3>
                  Revisión asistida de documentos sospechosos
                </h3>

                <p>
                  Compara un documento sospechoso con las referencias registradas
                  y prioriza los candidatos que deberían revisarse primero.
                </p>
              </div>

              {canRunTopK && (
                <>
                  <div className="workflow-steps">
                    <div className="workflow-step">
                      <span className="workflow-number">1</span>

                      <div>
                        <strong>Selecciona el documento</strong>
                        <p>
                          Carga el archivo sospechoso que deseas revisar.
                        </p>
                      </div>
                    </div>

                    <div className="workflow-step">
                      <span className="workflow-number">2</span>

                      <div>
                        <strong>ForensiQ lo compara</strong>
                        <p>
                          El sistema calcula su similitud frente a las referencias
                          disponibles.
                        </p>
                      </div>
                    </div>

                    <div className="workflow-step">
                      <span className="workflow-number">3</span>

                      <div>
                        <strong>Revisa los candidatos</strong>
                        <p>
                          Los resultados aparecen ordenados por similitud textual.
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="home-ranking-note">
                    <div>
                      <strong>¿Qué determina el orden?</strong>

                      <p>
                        La similitud textual determina la posición de cada candidato.
                        La estructura visual y el contexto PII se presentan como
                        evidencia auxiliar.
                      </p>
                    </div>
                  </div>

                  <div className="home-primary-action">
                    <button
                      className="primary"
                      onClick={openForensicSection}
                    >
                      Analizar un documento
                    </button>

                    <span>
                      El sistema apoya la revisión del analista y no emite una
                      decisión automática de correspondencia.
                    </span>
                  </div>
                </>
              )}

              {isDpo && (
                <div className="dpo-home">
                  <div className="workflow-step">
                    <span className="workflow-number">1</span>

                    <div>
                      <strong>Consulta los análisis registrados</strong>
                      <p>
                        Revisa los casos procesados y la información contextual
                        disponible de acuerdo con tu perfil.
                      </p>
                    </div>
                  </div>

                  <button
                    className="primary"
                    onClick={openHistorySection}
                  >
                    Revisar historial
                  </button>
                </div>
              )}
            </section>
          </main>
        )}
        {activeSection === "forensic" && !isAnalyst && (
          <main className="history-layout">
            <section className="panel full-panel">
              <PanelHeader title="Acceso restringido" badge="DPO" />
              <p className="muted">Tu rol puede revisar historial y señales PII, pero no ejecutar matching ni administrar el índice.</p>
            </section>
          </main>
        )}

        {activeSection === "forensic" && isAnalyst && (
  <main className="history-layout">
    <section className="panel full-panel">
      <PanelHeader
        title="Analizar documento sospechoso"
        badge="Top-5"
      />

      <p>
        Selecciona un documento sospechoso. ForensiQ lo comparará con los
        documentos de referencia disponibles y mostrará los candidatos que
        deberían revisarse primero.
      </p>

<div className="analysis-upload">
  <input
    id="suspicious-document-input"
    className="file-input-hidden"
    type="file"
    accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
    onChange={(event) => {
      const file = event.target.files?.[0] || null;
      setSuspiciousFile(file);
      setMatchResult(null);
      setMessage("");
    }}
  />

  {!suspiciousFile ? (
    <label
  htmlFor="suspicious-document-input"
  className="upload-dropzone"
  role="button"
  tabIndex={0}
  onKeyDown={(event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();

      document
        .getElementById("suspicious-document-input")
        ?.click();
    }
  }}
>
      <span className="upload-symbol">+</span>

      <strong>Selecciona un documento sospechoso</strong>

      <span>
        PDF, DOCX, TXT, JPG, PNG o JPEG
      </span>

      <span className="upload-action">
        Seleccionar archivo
      </span>
    </label>
  ) : (
    <div className="selected-file-card">
      <div className="selected-file-icon">
        DOC
      </div>

      <div className="selected-file-info">
        <strong>{suspiciousFile.name}</strong>

        <span>
          {suspiciousFile.name.split(".").pop()?.toUpperCase() || "Archivo"}
          {" · "}
          {formatFileSize(suspiciousFile.size)}
        </span>
      </div>

      <label
  htmlFor="suspicious-document-input"
  className="change-file-button"
  role="button"
  tabIndex={0}
  onKeyDown={(event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();

      document
        .getElementById("suspicious-document-input")
        ?.click();
    }
  }}
>
  Cambiar
</label>
    </div>
  )}
</div>

      <button
        className="primary full"
        onClick={matchSuspiciousDocument}
        disabled={!suspiciousFile || loading}
      >
        {loading ? "Analizando..." : "Analizar documento"}
      </button>

      <p className="muted small-note">
        ForensiQ genera un ranking para apoyar la revisión. El sistema no
        determina automáticamente que dos documentos sean idénticos.
      </p>
    </section>

    {matchResult && (
      <>
        <section className="panel full-panel">
          <PanelHeader
            title="Resumen del análisis"
            badge="Completado"
          />

          <EvidencePanel result={matchResult} />
        </section>

        <section className="panel full-panel">
          <PanelHeader
            title="Candidatos para revisión"
            badge={`${matchResult.matches?.length ?? 0} encontrados`}
          />

          <MatchResults result={matchResult} />
        </section>
      </>
    )}
  </main>
)}
{activeSection === "references" && isAnalyst && (
  <main className="history-layout">
    <section className="panel full-panel">
      <div className="reference-heading">
        <div>
          <span className="home-eyebrow">
            Corpus de comparación
          </span>

          <h3>Documentos de referencia</h3>

          <p>
            ForensiQ compara los documentos sospechosos contra estas
            referencias para generar el ranking de candidatos.
          </p>
        </div>

        <div className="reference-count">
          <strong>{referenceTotal}</strong>
          <span>referencias</span>
        </div>
      </div>

      {!isAdmin && (
        <div className="reference-readonly-note">
          <strong>Modo consulta</strong>

          <p>
            Tu perfil puede consultar las referencias disponibles.
            La incorporación, reconstrucción o eliminación está reservada
            al administrador.
          </p>
        </div>
      )}

      {isAdmin && (
        <div className="reference-admin-zone">
          <div className="reference-admin-heading">
            <div>
              <strong>Administración de referencias</strong>

              <p>
                Agrega documentos legítimos o realiza operaciones de
                mantenimiento sobre el corpus de comparación.
              </p>
            </div>

            <span>ADMIN</span>
          </div>

          <div className="upload-box reference-upload">
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
              disabled={loading}
              onChange={(event) =>
                setReferenceFiles(
                  Array.from(event.target.files || [])
                )
              }
            />

            <span>
              {referenceFiles.length
                ? `${referenceFiles.length} documento(s) seleccionado(s)`
                : "Selecciona documentos legítimos para agregarlos como referencia"}
            </span>

            {referenceFiles.length > 0 && (
              <div className="selected-files">
                {referenceFiles.slice(0, 5).map((file) => (
                  <span key={file.name}>
                    {file.name}
                  </span>
                ))}

                {referenceFiles.length > 5 && (
                  <span>
                    + {referenceFiles.length - 5} archivo(s) más
                  </span>
                )}
              </div>
            )}

            <button
              className="primary full"
              onClick={uploadReferenceDocuments}
              disabled={!referenceFiles.length || loading}
            >
              {loading
                ? "Procesando..."
                : "Agregar documentos de referencia"}
            </button>
          </div>

          <div className="reference-maintenance">
            <div>
              <strong>Mantenimiento</strong>

              <p>
                Utiliza estas acciones únicamente cuando sea necesario
                actualizar el corpus de referencia.
              </p>
            </div>

            <div className="toolbar">
              <button
                onClick={loadReferencesFromDb}
                disabled={loading}
              >
                Reconstruir índice
              </button>

              <button
                className="danger"
                onClick={clearReferences}
                disabled={loading || referenceTotal === 0}
              >
                Eliminar todas las referencias
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="reference-list-heading">
        <div>
          <strong>Referencias disponibles</strong>
          <p>
            Documentos actualmente considerados durante la comparación.
          </p>
        </div>

        <button
          onClick={fetchReferences}
          disabled={loading}
        >
          Actualizar
        </button>
      </div>

      <ReferenceTable references={references} />
    </section>
  </main>
)}
        {activeSection === "evaluation" && !isAdmin && (
          <main className="history-layout">
            <section className="panel full-panel">
              <PanelHeader title="Acceso restringido" badge="ADMIN" />
              <p className="muted">La evaluación experimental y la generación de corpus sintético están reservadas al administrador.</p>
            </section>
          </main>
        )}

        {activeSection === "evaluation" && isAdmin && (
          <main className="evaluation-layout">
            <section className="panel">
  <PanelHeader
    title="Simulación controlada"
    badge="Experimental"
  />

  <p className="muted">
    Genera una variante alterada de una referencia conocida y verifica
    su recuperación en el ranking. Esta función se utiliza únicamente
    para validación técnica.
  </p>

  <label className="field">
    Documento base

    <select
      value={selectedReferenceId}
      onChange={(event) =>
        setSelectedReferenceId(event.target.value)
      }
    >
      <option value="">
        Selecciona un documento
      </option>

      {references.map((doc) => (
        <option
          key={doc.document_id}
          value={doc.document_id}
        >
          {doc.filename}
        </option>
      ))}
    </select>
  </label>

  <label className="field">
    Transformación

    <select
      value={selectedTransformation}
      onChange={(event) =>
        setSelectedTransformation(event.target.value)
      }
    >
      {TRANSFORMATION_GROUPS.map((group) => (
        <optgroup
          key={group.label}
          label={group.label}
        >
          {group.options.map(([value, label]) => (
            <option
              key={value}
              value={value}
            >
              {label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  </label>

  <button
    className="primary full"
    onClick={generateVariantAndMatch}
  >
    Generar variante y comparar
  </button>

  {variantMatchResult && (
    <ControlledTestResult result={variantMatchResult} />
  )}
            </section>
            <section className="panel">
  <PanelHeader
    title="Configuración experimental"
    badge="Técnico"
  />

  <p className="muted">
    Información técnica disponible para reproducibilidad y evaluación
    del prototipo. No forma parte de la interpretación productiva
    del ranking.
  </p>

  <PipelineStatus />
</section>
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
              title="Historial de análisis"
              badge={`${historyTotal} casos`}
            />

            <p className="muted">
              Consulta los documentos procesados y revisa los candidatos registrados
              en cada análisis.
            </p>

              <div className="toolbar">
                <button onClick={fetchAnalysisHistory}>Actualizar</button>
                {isAdmin && (
                  <button
  className="danger"
  onClick={clearAnalysisHistory}
  disabled={loading || historyTotal === 0}
>
  Eliminar historial
</button>
                )}
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

function LoginScreen({
  loginForm,
  setLoginForm,
  onSubmit,
  loading,
  loginError,
}) {
  return (
    <div className="login-shell">
      <section className="login-card">
        <div className="brand login-brand">
          <div className="brand-icon">FQ</div>

          <div>
            <h1>ForensiQ</h1>
            <span>Revisión forense asistida de documentos</span>
          </div>
        </div>

        <p className="muted">
          Inicia sesión con las credenciales asignadas para acceder a las
          funciones correspondientes a tu perfil.
        </p>

        <form onSubmit={onSubmit} className="login-form">
          <label className="field">
            Correo electrónico

            <input
              type="email"
              value={loginForm.username}
              onChange={(event) =>
                setLoginForm({
                  ...loginForm,
                  username: event.target.value,
                })
              }
              placeholder="correo@organizacion.com"
              autoComplete="username"
              required
            />
          </label>

          <label className="field">
            Contraseña

            <input
              type="password"
              value={loginForm.password}
              onChange={(event) =>
                setLoginForm({
                  ...loginForm,
                  password: event.target.value,
                })
              }
              placeholder="Ingresa tu contraseña"
              autoComplete="current-password"
              required
            />
          </label>

          {loginError && (
            <div className="message error">
              {loginError}
            </div>
          )}

          <button
            className="primary full"
            type="submit"
            disabled={loading}
          >
            {loading ? "Ingresando..." : "Iniciar sesión"}
          </button>
        </form>
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
    return (
      <div className="reference-empty">
        <strong>No hay documentos de referencia disponibles</strong>

        <p>
          El sistema necesita referencias registradas para comparar
          documentos sospechosos.
        </p>
      </div>
    );
  }

  return (
    <div className="reference-list">
      {references.map((doc) => (
        <article
          className="reference-card"
          key={doc.document_id}
        >
          <div className="reference-icon">
            REF
          </div>

          <div className="reference-content">
            <span>Documento de referencia</span>

            <strong title={doc.filename}>
              {doc.filename}
            </strong>

            <div className="reference-meta">
              <span>
                Texto extraído:{" "}
                <strong>
                  {Number(doc.text_length || 0).toLocaleString()} caracteres
                </strong>
              </span>

              <span>
                Datos personales detectados:{" "}
                <strong>{doc.pii_count ?? 0}</strong>
              </span>
            </div>
          </div>

          <span className="reference-status">
            Disponible
          </span>
        </article>
      ))}
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
  const matches = result.matches || [];
  const best = matches[0];

  const rankingScore =
    best?.scores?.ranking_score ??
    best?.scores?.text_score;

  return (
    <div className="analysis-summary">
      <div className="analysis-success">
        <div className="analysis-success-icon">✓</div>

        <div>
          <strong>Análisis completado</strong>
          <span>
            ForensiQ encontró {matches.length} candidato
            {matches.length === 1 ? "" : "s"} para revisión.
          </span>
        </div>
      </div>

      <div className="analysis-summary-grid">
        <div className="analysis-summary-item">
          <span>Documento analizado</span>
          <strong title={result.filename}>
            {result.filename}
          </strong>
        </div>

        <div className="analysis-summary-item">
          <span>Candidatos encontrados</span>
          <strong>{matches.length}</strong>
        </div>

        <div className="analysis-summary-item primary-result">
          <span>Primer candidato</span>
          <strong>
            {best?.filename || "Sin candidato"}
          </strong>
        </div>

        <div className="analysis-summary-item primary-result">
          <span>Similitud textual</span>
          <strong>
            {best ? formatScore(rankingScore) : "—"}
          </strong>
        </div>
      </div>

      {best && (
        <div className="ranking-explanation">
          <strong>
            ¿Cómo interpretar este resultado?
          </strong>

          <p>
            El primer candidato ocupa la posición #1 porque presenta la
            mayor similitud textual dentro de los documentos evaluados.
          </p>

          <div className="ranking-signals">
            <div className="ranking-signal-main">
              <span>Determina el ranking</span>
              <strong>
                Similitud textual · {formatScore(rankingScore)}
              </strong>
            </div>

            <div>
              <span>Evidencia auxiliar</span>
              <strong>
                Layout · {formatScore(best.scores?.layout_score)}
              </strong>
            </div>

            <div>
              <span>Evidencia auxiliar</span>
              <strong>
                Contexto PII · {formatScore(best.scores?.pii_context_score)}
              </strong>
            </div>
          </div>
        </div>
      )}

      <details className="technical-details">
        <summary>
          Ver detalles técnicos del análisis
        </summary>

        <div className="technical-grid">
          <div>
            <span>PII detectada</span>
            <strong>{result.pii_count ?? 0}</strong>
          </div>

          <div>
            <span>Modo de extracción</span>
            <strong>
              {formatExtractionMode(result.extraction_mode)}
            </strong>
          </div>

          <div>
            <span>OCR utilizado</span>
            <strong>
              {result.ocr_used ? "Sí" : "No"}
            </strong>
          </div>

          <div>
            <span>Longitud de texto</span>
            <strong>
              {result.text_length ?? 0} caracteres
            </strong>
          </div>
        </div>

        {result.nlp_entities?.length > 0 && (
          <EntityPreview
            title="Información contextual detectada"
            entities={result.nlp_entities}
          />
        )}
      </details>

      <div className="analysis-export">
        <button
          onClick={() =>
            downloadJson(
              result,
              `forensiq_analysis_${safeFilename(result.filename)}.json`
            )
          }
        >
          Exportar detalle técnico
        </button>
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
function MatchResults({ result }) {
  const matches = result.matches || [];

  if (matches.length === 0) {
    return (
      <div className="results-empty">
        <strong>No se encontraron candidatos.</strong>
        <p>
          El análisis terminó correctamente, pero no se obtuvieron
          documentos candidatos para revisión.
        </p>
      </div>
    );
  }

  return (
    <div className="results-block">
      <div className="results-intro">
        <strong>
          {matches.length} candidato{matches.length === 1 ? "" : "s"} para revisión
        </strong>

        <p className="muted">
          El orden se determina por similitud textual. La evidencia de
          estructura visual y contexto PII sirve únicamente como apoyo
          para la revisión.
        </p>
      </div>

      <div className="candidate-list">
        {matches.map((match, index) => {
          const rankingScore =
            match.scores?.ranking_score ??
            match.scores?.text_score ??
            0;

          const numericScore = Number(rankingScore) || 0;

          const scoreWidth = Math.max(
            0,
            Math.min(100, numericScore * 100)
          );

          return (
            <article
              className={`candidate-card ${
                index === 0 ? "candidate-card-best" : ""
              }`}
              key={match.document_id}
            >
              <div className="candidate-header">
                <div className="candidate-position">
                  #{index + 1}
                </div>

                <div className="candidate-document">
                  <span>
                    {index === 0
                      ? "Primer candidato"
                      : "Candidato para revisión"}
                  </span>

                  <strong title={match.filename}>
                    {match.filename}
                  </strong>
                </div>

                {index === 0 && (
                  <span className="candidate-best-badge">
                    Mayor similitud
                  </span>
                )}
              </div>

              <div className="candidate-main-score">
                <div>
                  <span>Similitud textual</span>
                  <strong>{formatScore(rankingScore)}</strong>
                </div>

                <div
  className="score-meter"
  role="progressbar"
  aria-label="Similitud textual"
  aria-valuemin={0}
  aria-valuemax={100}
  aria-valuenow={Math.round(scoreWidth)}
>
                  <div
                    className="score-meter-fill"
                    style={{ width: `${scoreWidth}%` }}
                  />
                </div>
              </div>

              <div className="candidate-auxiliary">
                <div>
                  <span>Estructura visual</span>
                  <strong>
                    {formatScore(match.scores?.layout_score)}
                  </strong>
                  <small>Auxiliar</small>
                </div>

                <div>
                  <span>Contexto PII</span>
                  <strong>
                    {formatScore(match.scores?.pii_context_score)}
                  </strong>
                  <small>Auxiliar</small>
                </div>
              </div>

              <details className="candidate-details">
                <summary>
                  ¿Por qué aparece en esta posición?
                </summary>

                <div className="candidate-explanation">
                  <p>
                    <strong>Orden del ranking:</strong>{" "}
                    este candidato ocupa la posición #{index + 1} de
                    acuerdo con su similitud textual.
                  </p>

                  {match.analyst_explanation?.explanation && (
                    <p>
                      {match.analyst_explanation.explanation}
                    </p>
                  )}

                  <p className="muted">
                    La estructura visual y el contexto PII ayudan al
                    analista a interpretar el candidato, pero no modifican
                    su posición.
                  </p>
                </div>
              </details>
            </article>
          );
        })}
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
    return (
      <div className="history-empty">
        <strong>No hay análisis registrados</strong>
        <p>
          Cuando se procesen documentos sospechosos, los casos aparecerán
          aquí para su revisión.
        </p>
      </div>
    );
  }

  return (
    <div className="history-card-list">
      {items.map((item) => {
        const rankingScore =
          item.best_match_ranking_score ??
          item.best_match_score;

        return (
          <article
            className="history-card"
            key={item.id}
          >
            <div className="history-card-header">
              <div className="history-case-number">
                #{item.id}
              </div>

              <div className="history-card-title">
                <span>
                  {formatDate(item.created_at)}
                </span>

                <strong title={item.filename}>
                  {item.filename}
                </strong>
              </div>

              <span className="history-file-type">
                {item.file_type || "Archivo"}
              </span>
            </div>

            <div className="history-card-result">
              <div>
                <span>Primer candidato</span>

                <strong title={item.best_match_filename || ""}>
                  {item.best_match_filename || "Sin candidato"}
                </strong>
              </div>

              <div className="history-score">
                <span>Similitud textual</span>

                <strong>
                  {formatScore(rankingScore)}
                </strong>
              </div>
            </div>

            <div className="history-card-meta">
              <span>
                PII detectada: <strong>{item.pii_count ?? 0}</strong>
              </span>

              <span>
                Latencia:{" "}
                <strong>
                  {item.latency_ms
                    ? `${item.latency_ms} ms`
                    : "No disponible"}
                </strong>
              </span>
            </div>

            <div className="history-card-action">
              <button
                className="primary"
                onClick={() => onSelectItem(item)}
              >
                Revisar caso
              </button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function HistoryDetail({ item }) {
  const matches = item.matches || [];

  const bestRankingScore =
    item.best_match_ranking_score ??
    item.best_match_score;

  return (
    <div className="history-detail-v2">
      <div className="history-detail-heading">
        <div>
          <span className="home-eyebrow">
            Caso #{item.id}
          </span>

          <h4>
            Revisión del análisis
          </h4>

          <p>
            Consulta el documento procesado, el candidato principal y el
            ranking registrado durante el análisis.
          </p>
        </div>

        <span className="history-detail-date">
          {formatDate(item.created_at)}
        </span>
      </div>

      <div className="history-overview-grid">
        <div>
          <span>Documento analizado</span>

          <strong title={item.filename}>
            {item.filename}
          </strong>
        </div>

        <div>
          <span>Primer candidato</span>

          <strong title={item.best_match_filename || ""}>
            {item.best_match_filename || "Sin candidato"}
          </strong>
        </div>

        <div className="history-primary-metric">
          <span>Similitud textual</span>

          <strong>
            {formatScore(bestRankingScore)}
          </strong>
        </div>

        <div>
          <span>Candidatos registrados</span>

          <strong>{matches.length}</strong>
        </div>
      </div>

      <div className="history-context-note">
        <strong>Interpretación</strong>

        <p>
          Los candidatos fueron ordenados por similitud textual.
          La información de layout y contexto PII se conserva como
          evidencia auxiliar para apoyar la revisión.
        </p>
      </div>

      <details className="technical-details">
        <summary>
          Ver información técnica del caso
        </summary>

        <div className="technical-grid">
          <div>
            <span>Tipo de archivo</span>
            <strong>{item.file_type || "—"}</strong>
          </div>

          <div>
            <span>PII detectada</span>
            <strong>{item.pii_count ?? 0}</strong>
          </div>

          <div>
            <span>Latencia</span>
            <strong>
              {item.latency_ms
                ? `${item.latency_ms} ms`
                : "No disponible"}
            </strong>
          </div>

          <div>
            <span>Fecha</span>
            <strong>{formatDate(item.created_at)}</strong>
          </div>
        </div>
      </details>

      <div className="history-ranking-section">
        <div className="history-ranking-heading">
          <div>
            <strong>
              Candidatos del análisis
            </strong>

            <p>
              Ranking almacenado para este caso.
            </p>
          </div>

          <span>
            {matches.length} resultado
            {matches.length === 1 ? "" : "s"}
          </span>
        </div>

        {matches.length === 0 ? (
          <div className="history-empty">
            <strong>No hay candidatos almacenados</strong>
            <p>
              Este registro no contiene un ranking disponible para mostrar.
            </p>
          </div>
        ) : (
          <div className="candidate-list">
            {matches.map((match, index) => {
              /*
               * Compatibilidad con análisis anteriores al contrato
               * productivo oe3_production_v1.
               */
              const rankingScore =
                match.scores?.ranking_score ??
                match.scores?.text_score ??
                match.scores?.final_score ??
                0;

              const piiContextScore =
                match.scores?.pii_context_score ??
                match.scores?.pii_score;

              const numericScore = Number(rankingScore) || 0;

              const scoreWidth = Math.max(
                0,
                Math.min(100, numericScore * 100)
              );

              return (
                <article
                  className={`candidate-card ${
                    index === 0 ? "candidate-card-best" : ""
                  }`}
                  key={`${match.document_id}-${index}`}
                >
                  <div className="candidate-header">
                    <div className="candidate-position">
                      #{index + 1}
                    </div>

                    <div className="candidate-document">
                      <span>
                        {index === 0
                          ? "Primer candidato"
                          : "Candidato registrado"}
                      </span>

                      <strong title={match.filename}>
                        {match.filename}
                      </strong>
                    </div>

                    {index === 0 && (
                      <span className="candidate-best-badge">
                        Mayor similitud
                      </span>
                    )}
                  </div>

                  <div className="candidate-main-score">
                    <div>
                      <span>Similitud textual</span>

                      <strong>
                        {formatScore(rankingScore)}
                      </strong>
                    </div>

                    <div className="score-meter">
                      <div
                        className="score-meter-fill"
                        style={{
                          width: `${scoreWidth}%`,
                        }}
                      />
                    </div>
                  </div>

                  <div className="candidate-auxiliary">
                    <div>
                      <span>Estructura visual</span>

                      <strong>
                        {formatScore(
                          match.scores?.layout_score
                        )}
                      </strong>

                      <small>Auxiliar</small>
                    </div>

                    <div>
                      <span>Contexto PII</span>

                      <strong>
                        {formatScore(piiContextScore)}
                      </strong>

                      <small>Auxiliar</small>
                    </div>
                  </div>

                  {match.analyst_explanation?.explanation && (
                    <details className="candidate-details">
                      <summary>
                        Ver explicación registrada
                      </summary>

                      <div className="candidate-explanation">
                        <p>
                          {match.analyst_explanation.explanation}
                        </p>
                      </div>
                    </details>
                  )}
                </article>
              );
            })}
          </div>
        )}
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
function formatFileSize(bytes) {
  const value = Number(bytes);

  if (!Number.isFinite(value) || value <= 0) {
    return "Tamaño no disponible";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }

  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
