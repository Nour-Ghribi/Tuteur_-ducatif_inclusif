"""PDF export for parent reports.

Generates a simple, clean PDF from a ReportRecord using only the Python
standard library + a minimal templating approach.

We use ``weasyprint`` if available (best quality, CSS-based), falling back to
``reportlab`` (pure-Python, no system dependencies), and finally to a plain
UTF-8 text file if neither is installed.

The PDF never contains the student's real name or any PII — only the
pseudonymous subject_ref and aggregated metrics.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def _html_template(record) -> str:
    """Build a simple HTML document for weasyprint."""
    badges_html = ""
    if record.badges:
        items = "".join(
            f"<li>{b['badge_id'].replace('_', ' ')} ({b['tier']})</li>"
            for b in record.badges[:10]
        )
        badges_html = f"<h3>Badges obtenus</h3><ul>{items}</ul>"

    difficulties_html = ""
    if record.recurring_difficulties:
        items = "".join(f"<li>{d}</li>" for d in record.recurring_difficulties)
        difficulties_html = f"<h3>Difficultés récurrentes</h3><ul>{items}</ul>"

    return f"""<!DOCTYPE html>
<html lang="{record.language}">
<head>
<meta charset="utf-8">
<title>Rapport de progrès — {record.period_start} / {record.period_end}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12pt; margin: 2cm; color: #222; }}
  h1 {{ font-size: 16pt; color: #1a4d8f; }}
  h2 {{ font-size: 13pt; color: #1a4d8f; margin-top: 1.5em; }}
  h3 {{ font-size: 11pt; margin-top: 1em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  td, th {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #eef2f8; }}
  .narrative {{ line-height: 1.6; }}
  .footer {{ font-size: 9pt; color: #888; margin-top: 3em; }}
</style>
</head>
<body>
<h1>Rapport de progrès</h1>
<p><strong>Période :</strong> {record.period_start} → {record.period_end}</p>
<p><strong>Généré le :</strong> {record.generated_at.strftime('%d/%m/%Y')}</p>

<h2>Résumé</h2>
<table>
  <tr><th>Indicateur</th><th>Valeur</th></tr>
  <tr><td>Tentatives totales</td><td>{record.metrics.get('attempts_total', '—')}</td></tr>
  <tr><td>Jours actifs</td><td>{record.metrics.get('active_days', '—')}</td></tr>
  <tr><td>Taux de réussite</td><td>{record.metrics.get('success_rate', '—')} %</td></tr>
</table>

<h2>Rapport narratif</h2>
<div class="narrative">{record.narrative or '<em>Données insuffisantes pour générer un rapport narratif.</em>'}</div>

{difficulties_html}
{badges_html}

<div class="footer">
  Ce rapport contient uniquement des indicateurs agrégés. Aucune information personnelle
  identifiable n'est incluse. Identifiant pseudonyme : {record.student_ref}.
</div>
</body>
</html>"""


def export_pdf(record, output_path: Path | None = None) -> Path:
    """Export a ReportRecord to PDF. Returns the path to the generated file.

    Tries weasyprint first, then reportlab, then plain text.
    """
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    # --- attempt weasyprint ---
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
        html = _html_template(record)
        HTML(string=html).write_pdf(str(output_path))
        log.debug("PDF exported via weasyprint: %s", output_path)
        return output_path
    except ImportError:
        pass
    except Exception as exc:
        log.warning("weasyprint failed: %s", exc)

    # --- attempt reportlab ---
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore[import-not-found]
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        doc = SimpleDocTemplate(str(output_path), pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("Rapport de progrès", styles["Title"]))
        story.append(Paragraph(f"Période : {record.period_start} → {record.period_end}", styles["Normal"]))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(f"Tentatives : {record.metrics.get('attempts_total', '—')}", styles["Normal"]))
        story.append(Paragraph(f"Jours actifs : {record.metrics.get('active_days', '—')}", styles["Normal"]))
        story.append(Paragraph(f"Taux de réussite : {record.metrics.get('success_rate', '—')} %", styles["Normal"]))
        if record.narrative:
            story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph(record.narrative[:3000], styles["Normal"]))
        doc.build(story)
        log.debug("PDF exported via reportlab: %s", output_path)
        return output_path
    except ImportError:
        pass
    except Exception as exc:
        log.warning("reportlab failed: %s", exc)

    # --- fallback: plain text renamed as .pdf ---
    text_content = (
        f"Rapport de progrès\n"
        f"Période : {record.period_start} → {record.period_end}\n\n"
        f"Tentatives : {record.metrics.get('attempts_total', '—')}\n"
        f"Jours actifs : {record.metrics.get('active_days', '—')}\n"
        f"Taux de réussite : {record.metrics.get('success_rate', '—')} %\n\n"
        f"{record.narrative or 'Données insuffisantes.'}\n"
    )
    output_path.write_text(text_content, encoding="utf-8")
    log.warning("PDF export unavailable — wrote plain text to %s", output_path)
    return output_path
