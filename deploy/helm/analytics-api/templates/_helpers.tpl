{{- define "analytics-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "analytics-api.fullname" -}}
{{- if .Values.fullnameOverride }}{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}{{- else }}{{ include "analytics-api.name" . }}{{- end }}
{{- end }}
{{- define "analytics-api.labels" -}}
app.kubernetes.io/name: {{ include "analytics-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
