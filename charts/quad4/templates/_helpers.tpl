{{/*
Expand the name of the chart.
*/}}
{{- define "quad4.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "quad4.fullname" -}}
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
Common labels
*/}}
{{- define "quad4.labels" -}}
helm.sh/chart: {{ include "quad4.chart" . }}
app.kubernetes.io/name: {{ include "quad4.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "quad4.selectorLabels" -}}
app.kubernetes.io/name: {{ include "quad4.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "quad4.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "quad4.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "quad4.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Compute the frontend URL based on global.domain and global.tls
*/}}
{{- define "quad4.frontendUrl" -}}
{{- if .Values.global.tls -}}
https://{{ .Values.global.domain }}
{{- else -}}
http://{{ .Values.global.domain }}
{{- end -}}
{{- end -}}

{{/*
Compute the default OAuth Redirect URI
*/}}
{{- define "quad4.oauthRedirectUri" -}}
{{ include "quad4.frontendUrl" . }}/oauth/callback
{{- end -}}
