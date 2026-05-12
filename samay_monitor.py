#!/usr/bin/env python3
"""
SAMAY - Meta Ads Performance Monitor
Sistema de alertas como Media Buyer experto
Corre automáticamente y analiza campañas con IA
"""

import requests
import json
import smtplib
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============================================================
# CONFIGURACIÓN — editá estos valores
# ============================================================

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_122704474782900")

# Alertas por email (opcional)
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")

# Anthropic API para análisis con IA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ============================================================
# UMBRALES DE ALERTA — ajustá según tu negocio
# ============================================================

THRESHOLDS = {
    # RENDIMIENTO
    "ctr_min": 1.0,              # CTR mínimo aceptable (%)
    "cpc_max": 5.0,              # CPC máximo aceptable (USD)
    "cpm_max": 15.0,             # CPM máximo aceptable (USD)
    "cpa_max": 50.0,             # CPA máximo aceptable (USD)
    "roas_min": 2.0,             # ROAS mínimo aceptable
    "frequency_max": 4.0,        # Frecuencia máxima (fatiga de audiencia)

    # PRESUPUESTO
    "budget_spent_warning": 0.80, # Alerta cuando gastó 80% del presupuesto
    "budget_spent_critical": 0.95,# Crítico cuando gastó 95% del presupuesto

    # CONVERSIONES
    "zero_conversions_hours": 24, # Alerta si 0 conversiones en X horas
    "conversion_drop_pct": 30,    # Alerta si conversiones caen X%

    # GASTO ANÓMALO
    "spend_spike_pct": 50,        # Alerta si gasto sube X% vs día anterior

    # CALIDAD
    "relevance_score_min": 3,     # Score de relevancia mínimo (1-10)
    "quality_ranking_bad": "BELOW_AVERAGE",  # Ranking de calidad mínimo
}

# ============================================================
# FUNCIONES DE META API
# ============================================================

BASE_URL = "https://graph.facebook.com/v19.0"

def get_campaigns():
    """Obtiene todas las campañas activas"""
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,daily_budget,lifetime_budget,objective,start_time,stop_time",
        "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
        "limit": 100
    }
    r = requests.get(url, params=params)
    return r.json().get("data", [])

def get_campaign_insights(campaign_id, date_preset="today"):
    """Obtiene métricas de una campaña"""
    url = f"{BASE_URL}/{campaign_id}/insights"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": (
            "campaign_name,impressions,clicks,spend,ctr,cpc,cpm,"
            "actions,action_values,cost_per_action_type,"
            "frequency,reach,unique_clicks,cpp,"
            "quality_ranking,engagement_rate_ranking,conversion_rate_ranking"
        ),
        "date_preset": date_preset,
        "level": "campaign"
    }
    r = requests.get(url, params=params)
    data = r.json().get("data", [])
    return data[0] if data else {}

def get_adsets(campaign_id):
    """Obtiene ad sets de una campaña"""
    url = f"{BASE_URL}/{campaign_id}/adsets"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,daily_budget,targeting,optimization_goal,billing_event",
        "limit": 100
    }
    r = requests.get(url, params=params)
    return r.json().get("data", [])

def get_ads_insights(campaign_id):
    """Obtiene métricas a nivel de anuncio"""
    url = f"{BASE_URL}/{campaign_id}/ads"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,effective_status,creative{thumbnail_url}",
        "limit": 100
    }
    r = requests.get(url, params=params)
    return r.json().get("data", [])

def pause_campaign(campaign_id):
    """Pausa una campaña automáticamente"""
    url = f"{BASE_URL}/{campaign_id}"
    params = {
        "access_token": ACCESS_TOKEN,
        "status": "PAUSED"
    }
    r = requests.post(url, params=params)
    return r.json()

# ============================================================
# ANÁLISIS CON IA (Claude)
# ============================================================

def analyze_with_ai(campaigns_data, alerts):
    """Usa Claude para analizar el estado general y dar recomendaciones"""
    if not ANTHROPIC_API_KEY:
        return None

    prompt = f"""
Sos un Media Buyer experto especializado en Meta Ads.
Analizá los siguientes datos de campañas y alertas detectadas.
Dá un diagnóstico claro y recomendaciones accionables.

DATOS DE CAMPAÑAS:
{json.dumps(campaigns_data, indent=2, ensure_ascii=False)}

ALERTAS DETECTADAS:
{json.dumps(alerts, indent=2, ensure_ascii=False)}

Respondé con:
1. DIAGNÓSTICO GENERAL (2-3 líneas)
2. ALERTAS CRÍTICAS a atender YA
3. OPTIMIZACIONES recomendadas esta semana
4. QUÉ está funcionando bien
5. PREDICCIÓN: si no se actúa, qué pasará

Sé directo y específico. Usá los nombres reales de las campañas.
"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    data = response.json()
    return data.get("content", [{}])[0].get("text", "")

# ============================================================
# SISTEMA DE ALERTAS
# ============================================================

def check_alerts(campaign, insights, yesterday_insights={}):
    """Evalúa todas las métricas y genera alertas"""
    alerts = []
    name = campaign.get("name", "Sin nombre")

    if not insights:
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "SIN DATOS",
            "mensaje": "No hay datos de insights para hoy. Puede estar inactiva o sin impresiones."
        })
        return alerts

    # Extraer métricas
    ctr = float(insights.get("ctr", 0))
    cpc = float(insights.get("cpc", 0))
    cpm = float(insights.get("cpm", 0))
    spend = float(insights.get("spend", 0))
    frequency = float(insights.get("frequency", 0))
    impressions = int(insights.get("impressions", 0))
    clicks = int(insights.get("clicks", 0))
    quality = insights.get("quality_ranking", "")
    engagement = insights.get("engagement_rate_ranking", "")
    conversion = insights.get("conversion_rate_ranking", "")

    # Extraer conversiones
    actions = insights.get("actions", [])
    conversions = sum(
        int(a.get("value", 0)) for a in actions
        if a.get("action_type") in ["purchase", "lead", "complete_registration", "offsite_conversion"]
    )

    # Extraer ROAS
    action_values = insights.get("action_values", [])
    revenue = sum(float(a.get("value", 0)) for a in action_values if a.get("action_type") == "purchase")
    roas = revenue / spend if spend > 0 else 0

    # Presupuesto
    daily_budget = float(campaign.get("daily_budget", 0)) / 100  # Meta lo devuelve en centavos
    lifetime_budget = float(campaign.get("lifetime_budget", 0)) / 100
    budget = daily_budget or lifetime_budget

    # ---- ALERTAS DE RENDIMIENTO ----

    if ctr > 0 and ctr < THRESHOLDS["ctr_min"]:
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "CTR BAJO",
            "mensaje": f"CTR de {ctr:.2f}% está por debajo del mínimo ({THRESHOLDS['ctr_min']}%). El creativo puede estar generando fatiga o no es relevante.",
            "valor": ctr,
            "umbral": THRESHOLDS["ctr_min"]
        })

    if cpc > THRESHOLDS["cpc_max"]:
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "CPC ALTO",
            "mensaje": f"CPC de ${cpc:.2f} supera el máximo (${THRESHOLDS['cpc_max']}). Revisá segmentación y creativos.",
            "valor": cpc,
            "umbral": THRESHOLDS["cpc_max"]
        })

    if cpm > THRESHOLDS["cpm_max"]:
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "CPM ALTO",
            "mensaje": f"CPM de ${cpm:.2f} es muy alto. La audiencia puede estar saturada o la puja muy agresiva.",
            "valor": cpm,
            "umbral": THRESHOLDS["cpm_max"]
        })

    if roas > 0 and roas < THRESHOLDS["roas_min"]:
        alerts.append({
            "level": "CRITICAL",
            "campaign": name,
            "tipo": "ROAS BAJO",
            "mensaje": f"ROAS de {roas:.2f}x está por debajo del mínimo ({THRESHOLDS['roas_min']}x). Estás perdiendo dinero.",
            "valor": roas,
            "umbral": THRESHOLDS["roas_min"]
        })

    if frequency > THRESHOLDS["frequency_max"]:
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "FATIGA DE AUDIENCIA",
            "mensaje": f"Frecuencia de {frequency:.1f}x supera el máximo ({THRESHOLDS['frequency_max']}x). La audiencia ya vio el anuncio demasiadas veces. Renovar creativos.",
            "valor": frequency,
            "umbral": THRESHOLDS["frequency_max"]
        })

    # ---- ALERTAS DE CONVERSIONES ----

    if impressions > 1000 and conversions == 0:
        alerts.append({
            "level": "CRITICAL",
            "campaign": name,
            "tipo": "CERO CONVERSIONES",
            "mensaje": f"La campaña tuvo {impressions:,} impresiones hoy pero 0 conversiones. Revisá el píxel, la landing page y el objetivo.",
            "valor": 0,
            "umbral": 1
        })

    # ---- ALERTAS DE PRESUPUESTO ----

    if budget > 0:
        spent_ratio = spend / budget
        if spent_ratio >= THRESHOLDS["budget_spent_critical"]:
            alerts.append({
                "level": "CRITICAL",
                "campaign": name,
                "tipo": "PRESUPUESTO CASI AGOTADO",
                "mensaje": f"Gastó ${spend:.2f} de ${budget:.2f} ({spent_ratio*100:.0f}%). El presupuesto se agotará pronto.",
                "valor": spent_ratio * 100,
                "umbral": THRESHOLDS["budget_spent_critical"] * 100
            })
        elif spent_ratio >= THRESHOLDS["budget_spent_warning"]:
            alerts.append({
                "level": "WARNING",
                "campaign": name,
                "tipo": "PRESUPUESTO AL 80%",
                "mensaje": f"Gastó ${spend:.2f} de ${budget:.2f} ({spent_ratio*100:.0f}%). Considerá aumentar presupuesto si la campaña está funcionando.",
                "valor": spent_ratio * 100,
                "umbral": THRESHOLDS["budget_spent_warning"] * 100
            })

    # ---- ALERTAS DE CALIDAD ----

    if quality == "BELOW_AVERAGE":
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "CALIDAD DEL ANUNCIO BAJA",
            "mensaje": "El Quality Ranking está BELOW_AVERAGE. Meta penaliza este anuncio. Renovar creativos urgente.",
            "valor": quality,
            "umbral": "ABOVE_AVERAGE"
        })

    if engagement == "BELOW_AVERAGE":
        alerts.append({
            "level": "WARNING",
            "campaign": name,
            "tipo": "ENGAGEMENT BAJO",
            "mensaje": "El Engagement Rate Ranking está BELOW_AVERAGE. El contenido no está generando interacción.",
            "valor": engagement,
            "umbral": "ABOVE_AVERAGE"
        })

    if conversion == "BELOW_AVERAGE":
        alerts.append({
            "level": "CRITICAL",
            "campaign": name,
            "tipo": "TASA DE CONVERSIÓN BAJA",
            "mensaje": "El Conversion Rate Ranking está BELOW_AVERAGE. Revisá la landing page y el flujo de conversión.",
            "valor": conversion,
            "umbral": "ABOVE_AVERAGE"
        })

    # ---- CAMPAÑA SIN ACTIVIDAD ----

    if impressions == 0 and campaign.get("status") == "ACTIVE":
        alerts.append({
            "level": "CRITICAL",
            "campaign": name,
            "tipo": "CAMPAÑA ACTIVA SIN IMPRESIONES",
            "mensaje": "La campaña está ACTIVA pero no tuvo impresiones hoy. Puede haber un problema de aprobación, presupuesto o segmentación.",
            "valor": 0,
            "umbral": 1
        })

    return alerts

# ============================================================
# REPORTE Y NOTIFICACIONES
# ============================================================

def send_email(subject, body):
    """Envía email de alerta"""
    if not EMAIL_SENDER or not EMAIL_RECEIVER:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("✅ Email enviado")
    except Exception as e:
        print(f"❌ Error enviando email: {e}")

def build_report(campaigns_data, all_alerts, ai_analysis):
    """Construye el reporte HTML"""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    critical = [a for a in all_alerts if a["level"] == "CRITICAL"]
    warnings = [a for a in all_alerts if a["level"] == "WARNING"]

    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
    <h1 style="color: #1877F2;">📊 Samay — Reporte Meta Ads</h1>
    <p style="color: #666;">{now}</p>

    <div style="background: {'#ffebee' if critical else '#e8f5e9'}; padding: 15px; border-radius: 8px; margin: 20px 0;">
        <h2>{'🚨 ' + str(len(critical)) + ' ALERTAS CRÍTICAS' if critical else '✅ Sin alertas críticas'}</h2>
        <p>⚠️ {len(warnings)} advertencias</p>
    </div>
    """

    if ai_analysis:
        html += f"""
    <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
        <h2>🤖 Análisis de IA</h2>
        <pre style="white-space: pre-wrap; font-family: Arial;">{ai_analysis}</pre>
    </div>
    """

    if critical:
        html += "<h2>🚨 Alertas Críticas</h2>"
        for a in critical:
            html += f"""
    <div style="background: #ffcdd2; padding: 10px; border-radius: 6px; margin: 10px 0; border-left: 4px solid #f44336;">
        <strong>{a['campaign']}</strong> — {a['tipo']}<br>
        {a['mensaje']}
    </div>"""

    if warnings:
        html += "<h2>⚠️ Advertencias</h2>"
        for a in warnings:
            html += f"""
    <div style="background: #fff9c4; padding: 10px; border-radius: 6px; margin: 10px 0; border-left: 4px solid #ff9800;">
        <strong>{a['campaign']}</strong> — {a['tipo']}<br>
        {a['mensaje']}
    </div>"""

    html += "<h2>📈 Resumen de Campañas</h2><table style='width:100%; border-collapse: collapse;'>"
    html += "<tr style='background:#1877F2; color:white;'><th>Campaña</th><th>Gasto</th><th>CTR</th><th>CPC</th><th>ROAS</th><th>Frec.</th></tr>"

    for c in campaigns_data:
        i = c.get("insights", {})
        spend = float(i.get("spend", 0))
        ctr = float(i.get("ctr", 0))
        cpc = float(i.get("cpc", 0))
        actions = i.get("action_values", [])
        revenue = sum(float(a.get("value", 0)) for a in actions if a.get("action_type") == "purchase")
        roas = revenue / spend if spend > 0 else 0
        freq = float(i.get("frequency", 0))

        html += f"""
    <tr style='border-bottom: 1px solid #eee;'>
        <td style='padding:8px'>{c['name']}</td>
        <td style='padding:8px'>${spend:.2f}</td>
        <td style='padding:8px; color: {"green" if ctr >= THRESHOLDS["ctr_min"] else "red"}'>{ctr:.2f}%</td>
        <td style='padding:8px; color: {"green" if cpc <= THRESHOLDS["cpc_max"] else "red"}'>${cpc:.2f}</td>
        <td style='padding:8px; color: {"green" if roas >= THRESHOLDS["roas_min"] else "red"}'>{roas:.2f}x</td>
        <td style='padding:8px; color: {"green" if freq <= THRESHOLDS["frequency_max"] else "red"}'>{freq:.1f}x</td>
    </tr>"""

    html += "</table></body></html>"
    return html

# ============================================================
# MAIN — EJECUCIÓN PRINCIPAL
# ============================================================

def run_monitor():
    print(f"\n{'='*60}")
    print(f"🚀 SAMAY Monitor iniciado — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    campaigns = get_campaigns()
    print(f"📋 Campañas encontradas: {len(campaigns)}")

    all_alerts = []
    campaigns_data = []

    for campaign in campaigns:
        name = campaign.get("name", "Sin nombre")
        cid = campaign.get("id")
        status = campaign.get("status")
        print(f"\n🔍 Analizando: {name} [{status}]")

        insights = get_campaign_insights(cid, "today")
        alerts = check_alerts(campaign, insights)
        all_alerts.extend(alerts)

        campaigns_data.append({
            "id": cid,
            "name": name,
            "status": status,
            "insights": insights
        })

        if alerts:
            for a in alerts:
                icon = "🚨" if a["level"] == "CRITICAL" else "⚠️"
                print(f"  {icon} {a['tipo']}: {a['mensaje'][:80]}...")
        else:
            print(f"  ✅ Todo bien")

    # Análisis con IA
    print(f"\n🤖 Analizando con IA...")
    ai_analysis = analyze_with_ai(campaigns_data, all_alerts)
    if ai_analysis:
        print(f"\n{ai_analysis}")

    # Reporte
    critical_count = len([a for a in all_alerts if a["level"] == "CRITICAL"])
    warning_count = len([a for a in all_alerts if a["level"] == "WARNING"])

    print(f"\n{'='*60}")
    print(f"📊 RESUMEN FINAL")
    print(f"   🚨 Alertas críticas: {critical_count}")
    print(f"   ⚠️  Advertencias: {warning_count}")
    print(f"{'='*60}\n")

    # Enviar email si hay alertas
    if all_alerts:
        report_html = build_report(campaigns_data, all_alerts, ai_analysis)
        subject = f"🚨 Samay Ads — {critical_count} críticas, {warning_count} advertencias — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        send_email(subject, report_html)

    # Guardar reporte JSON
    with open("samay_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "campaigns": campaigns_data,
            "alerts": all_alerts,
            "ai_analysis": ai_analysis
        }, f, ensure_ascii=False, indent=2)

    print("💾 Reporte guardado en samay_report.json")

if __name__ == "__main__":
    run_monitor()
