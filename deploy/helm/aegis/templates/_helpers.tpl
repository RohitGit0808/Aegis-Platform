{{/*
Expand the name of the chart.
*/}}
{{- define "aegis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this
(by the DNS naming spec).
*/}}
{{- define "aegis.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "aegis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "aegis.labels" -}}
helm.sh/chart: {{ include "aegis.chart" . }}
{{ include "aegis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/part-of: aegis-platform
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (immutable; used by Deployments/Services/PDBs).
*/}}
{{- define "aegis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aegis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API component selector labels.
*/}}
{{- define "aegis.api.selectorLabels" -}}
{{ include "aegis.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker component selector labels.
*/}}
{{- define "aegis.worker.selectorLabels" -}}
{{ include "aegis.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Name of the service account to use.
*/}}
{{- define "aegis.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "aegis.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Fully-resolved container image reference.
*/}}
{{- define "aegis.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Name of the Secret backing AEGIS_* sensitive env (existing or chart-managed).
*/}}
{{- define "aegis.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "aegis.fullname" .) }}
{{- end }}
{{- end }}

{{/*
envFrom block shared by the API and worker containers.
*/}}
{{- define "aegis.envFrom" -}}
- configMapRef:
    name: {{ include "aegis.fullname" . }}-config
- secretRef:
    name: {{ include "aegis.secretName" . }}
{{- end }}
