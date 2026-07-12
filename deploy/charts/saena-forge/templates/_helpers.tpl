{{/*
Chart name (mirrors Helm's standard chart template helpers, scoped to
saena-forge — ADR-0005 confirmed chart identity).
*/}}
{{- define "saena-forge.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully-qualified release name.
*/}}
{{- define "saena-forge.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart label value (name-version).
*/}}
{{- define "saena-forge.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every resource this chart renders.
*/}}
{{- define "saena-forge.labels" -}}
helm.sh/chart: {{ include "saena-forge.chart" . }}
{{ include "saena-forge.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
saena.io/chart: saena-forge
{{- end -}}

{{/*
Selector labels — stable subset used by Service/Deployment/PDB selectors.
Callers pass a dict with `root` (the top `.`) and `service` (the per-service
values map key, e.g. "forgeConsoleApi") so the same helper renders both
chart-wide and per-service selector labels.
*/}}
{{- define "saena-forge.selectorLabels" -}}
app.kubernetes.io/name: {{ include "saena-forge.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Per-service selector labels. Usage: include "saena-forge.serviceSelectorLabels" (dict "root" $ "service" "forge-console-api")
*/}}
{{- define "saena-forge.serviceSelectorLabels" -}}
{{ include "saena-forge.selectorLabels" .root }}
app.kubernetes.io/component: {{ .service }}
{{- end -}}

{{/*
Per-service full labels (selector labels + version + part-of).
*/}}
{{- define "saena-forge.serviceLabels" -}}
{{ include "saena-forge.labels" .root }}
app.kubernetes.io/component: {{ .service }}
app.kubernetes.io/part-of: saena-forge
{{- end -}}

{{/*
Per-service resource name: <release-fullname>-<service>.
Usage: include "saena-forge.serviceFullname" (dict "root" $ "service" "forge-console-api")
*/}}
{{- define "saena-forge.serviceFullname" -}}
{{- printf "%s-%s" (include "saena-forge.fullname" .root) .service | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Per-service ServiceAccount name.
*/}}
{{- define "saena-forge.serviceAccountName" -}}
{{- printf "%s-sa" (include "saena-forge.serviceFullname" .) -}}
{{- end -}}

{{/*
Tenant namespace name — derived deterministically from tenant_id (ADR-0014
"namespace field must be derived, never an independent input"). Usage:
include "saena-forge.tenantNamespace" "<tenant_id>"
*/}}
{{- define "saena-forge.tenantNamespace" -}}
{{- printf "saena-tenant-%s" . | trunc 63 | trimSuffix "-" -}}
{{- end -}}
