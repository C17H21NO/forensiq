# =============================================================================
# ForensiQ - Política central de acceso (RBAC)
# =============================================================================

ROLE_ADMIN = "ADMIN"
ROLE_ANALYST = "ANALYST"
ROLE_DPO = "DPO"


# Cualquier usuario autenticado.
ALL_AUTHENTICATED_ROLES = (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_DPO,
)


# -----------------------------------------------------------------------------
# Gestión administrativa
# -----------------------------------------------------------------------------

USER_MANAGEMENT_ROLES = (
    ROLE_ADMIN,
)

REFERENCE_MANAGEMENT_ROLES = (
    ROLE_ADMIN,
)

HISTORY_MANAGEMENT_ROLES = (
    ROLE_ADMIN,
)


# -----------------------------------------------------------------------------
# Operación ForensiQ
# -----------------------------------------------------------------------------

DOCUMENT_ANALYSIS_ROLES = (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_DPO,
)

MATCHING_ROLES = (
    ROLE_ADMIN,
    ROLE_ANALYST,
)

REFERENCE_READ_ROLES = (
    ROLE_ADMIN,
    ROLE_ANALYST,
)


# -----------------------------------------------------------------------------
# Supervisión / trazabilidad
# -----------------------------------------------------------------------------

HISTORY_READ_ROLES = (
    ROLE_ADMIN,
    ROLE_DPO,
)

SYSTEM_INFORMATION_ROLES = (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_DPO,
)


# -----------------------------------------------------------------------------
# Funciones experimentales
#
# No forman parte del recorrido productivo de participantes OE3.
# -----------------------------------------------------------------------------

EXPERIMENTAL_ROLES = (
    ROLE_ADMIN,
)