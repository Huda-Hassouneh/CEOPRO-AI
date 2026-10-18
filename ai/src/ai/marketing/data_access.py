"""
KEEL - Automated Marketing System, Persistence.

Writes to `campaigns` (extended) and `campaign_content` (new) - see
migrations/20260925000000_add_marketing_campaign_content.sql for the
schema and the reasoning behind every column. Every function here takes
an already-open, already-tenant-scoped `conn` (db.app_role_connection()),
matching every other module in this service (products.py, dashboard/*) -
RLS does the actual tenant isolation, the explicit `tenant_id = %s`
filters here are defense in depth, same convention as products.py.
"""
import re
from typing import Optional

from src.ai.marketing.content_generator import GeneratedCampaign, without_fixed_labels

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Campaigns written before titles were cleaned up were saved as
# "Product name: X" (and "... (source: <link>)" for links).
_OLD_TITLE_LABEL = re.compile(r"^\s*product name:\s*", re.IGNORECASE)
_OLD_TITLE_SOURCE = re.compile(r"\s*\(source: [^)]*\)\s*$")


def campaign_title(campaign_brief: Optional[str]) -> Optional[str]:
    if not campaign_brief:
        return campaign_brief
    return _OLD_TITLE_SOURCE.sub("", _OLD_TITLE_LABEL.sub("", campaign_brief)).strip() or campaign_brief


def create_campaign(
    conn, tenant_id: str, user_id: Optional[str], *,
    product_id: Optional[str], input_source: str, campaign_brief: str,
    style: Optional[str], tone: Optional[str], focus: Optional[str], strategy_type: str,
    source_text: Optional[str], source_url: Optional[str],
    creative_theme: Optional[str], theme_source: Optional[str], custom_creative_prompt: Optional[str],
    request_key: Optional[str] = None,
) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO campaigns
                (tenant_id, product_id, campaign_brief, status, input_source, style, tone, focus,
                 strategy_type, source_text, source_url, creative_theme, theme_source, custom_creative_prompt, request_key)
            VALUES (%s, %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING campaign_id;
            """,
            (tenant_id, product_id, campaign_brief, input_source, style, tone, focus,
             strategy_type, source_text, source_url, creative_theme, theme_source, custom_creative_prompt, request_key),
        )
        return str(cursor.fetchone()[0])


def set_source_image_key(conn, tenant_id: str, campaign_id: str, image_key: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE campaigns SET source_image_key = %s WHERE tenant_id = %s AND campaign_id = %s RETURNING campaign_id;",
            (image_key, tenant_id, campaign_id),
        )
        return cursor.fetchone() is not None


def save_campaign_result(
    conn, tenant_id: str, campaign_id: str,
    positioning_label: Optional[str], generated: GeneratedCampaign,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE campaigns
            SET status = 'COMPLETED', audience_summary = %s, positioning_label = %s,
                creative_direction = %s, image_prompt = %s, completed_at = CURRENT_TIMESTAMP, error_message = NULL
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (generated.audience_summary, positioning_label, generated.creative_direction,
             getattr(generated, "image_prompt", None), tenant_id, campaign_id),
        )
        for platform, variants in generated.variants_by_platform.items():
            for index, variant in enumerate(variants, start=1):
                cursor.execute(
                    """
                    INSERT INTO campaign_content
                        (tenant_id, campaign_id, platform, variant_index, headline, body_copy, hashtags, cta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, campaign_id, platform, variant_index)
                    DO UPDATE SET headline = EXCLUDED.headline, body_copy = EXCLUDED.body_copy,
                                  hashtags = EXCLUDED.hashtags, cta = EXCLUDED.cta;
                    """,
                    (tenant_id, campaign_id, platform, index, variant.headline, variant.body_copy,
                     variant.hashtags, variant.cta),
                )


def save_generated_image(
    conn, tenant_id: str, campaign_id: str, *, provider: str, image_key: str,
    used_reference: bool = False, reference_note: Optional[str] = None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE campaigns
            SET generated_image_key = %s, image_generation_status = 'COMPLETED',
                image_generation_provider = %s, image_generation_error = NULL,
                image_generated_at = CURRENT_TIMESTAMP,
                image_generation_used_reference = %s, image_generation_reference_note = %s
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (image_key, provider, used_reference, reference_note, tenant_id, campaign_id),
        )


def save_image_generation_failure(conn, tenant_id: str, campaign_id: str, *, status: str, error_message: str, provider: Optional[str] = None) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE campaigns
            SET image_generation_status = %s, image_generation_provider = %s,
                image_generation_error = %s, image_generated_at = CURRENT_TIMESTAMP,
                image_generation_used_reference = FALSE, image_generation_reference_note = NULL
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (status, provider, error_message, tenant_id, campaign_id),
        )


def save_processed_image(conn, tenant_id: str, campaign_id: str, *, provider: str, image_key: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE campaigns
            SET source_image_processed_key = %s, background_removal_status = 'COMPLETED',
                background_removal_provider = %s, background_removal_error = NULL,
                background_removal_completed_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (image_key, provider, tenant_id, campaign_id),
        )


def save_background_removal_failure(conn, tenant_id: str, campaign_id: str, *, status: str, error_message: str, provider: Optional[str] = None) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE campaigns
            SET background_removal_status = %s, background_removal_provider = %s,
                background_removal_error = %s, background_removal_completed_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (status, provider, error_message, tenant_id, campaign_id),
        )


def set_reference_image_selection(conn, tenant_id: str, campaign_id: str, selection: Optional[str]) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE campaigns SET reference_image_selection = %s WHERE tenant_id = %s AND campaign_id = %s RETURNING campaign_id;",
            (selection, tenant_id, campaign_id),
        )
        return cursor.fetchone() is not None


def mark_campaign_failed(conn, tenant_id: str, campaign_id: str, error_message: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE campaigns SET status = 'FAILED', error_message = %s, completed_at = CURRENT_TIMESTAMP "
            "WHERE tenant_id = %s AND campaign_id = %s;",
            (error_message, tenant_id, campaign_id),
        )


def _content_rows_to_dict(rows) -> dict:
    by_platform: dict = {}
    for platform, variant_index, headline, body_copy, hashtags, cta in rows:
        by_platform.setdefault(platform, []).append({
            "variant_index": int(variant_index),
            "headline": headline,
            "body_copy": body_copy,
            "hashtags": list(hashtags or []),
            "cta": cta,
        })
    return by_platform


def get_campaign(conn, tenant_id: str, campaign_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT campaign_id, product_id, campaign_brief, status, input_source, style, tone, focus,
                   strategy_type, source_text, source_url, source_image_key, audience_summary,
                   positioning_label, error_message, requested_at, completed_at,
                   creative_theme, theme_source, custom_creative_prompt, creative_direction,
                   generated_image_key, image_generation_status, image_generation_provider,
                   image_generation_error, image_generated_at,
                   source_image_processed_key, background_removal_status, background_removal_provider,
                   background_removal_error, background_removal_completed_at, reference_image_selection,
                   image_generation_used_reference, image_generation_reference_note, image_prompt, updated_at
            FROM campaigns
            WHERE tenant_id = %s AND campaign_id = %s;
            """,
            (tenant_id, campaign_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        (
            cid, product_id, campaign_brief, status, input_source, style, tone, focus,
            strategy_type, source_text, source_url, source_image_key, audience_summary,
            positioning_label, error_message, requested_at, completed_at,
            creative_theme, theme_source, custom_creative_prompt, creative_direction,
            generated_image_key, image_generation_status, image_generation_provider,
            image_generation_error, image_generated_at,
            source_image_processed_key, background_removal_status, background_removal_provider,
            background_removal_error, background_removal_completed_at, reference_image_selection,
            image_generation_used_reference, image_generation_reference_note, image_prompt, updated_at,
        ) = row
        audience_summary, creative_direction = without_fixed_labels(audience_summary, creative_direction)

        cursor.execute(
            """
            SELECT platform, variant_index, headline, body_copy, hashtags, cta
            FROM campaign_content
            WHERE tenant_id = %s AND campaign_id = %s
            ORDER BY platform, variant_index;
            """,
            (tenant_id, campaign_id),
        )
        content_rows = cursor.fetchall()

    return {
        "campaign_id": str(cid),
        "product_id": str(product_id) if product_id else None,
        "campaign_brief": campaign_title(campaign_brief),
        "status": status,
        "input_source": input_source,
        "style": style,
        "tone": tone,
        "focus": focus,
        "strategy_type": strategy_type,
        "source_text": source_text,
        "source_url": source_url,
        "source_image_key": source_image_key,
        "audience_summary": audience_summary,
        "positioning_label": positioning_label,
        "error_message": error_message,
        "requested_at": requested_at.isoformat() if requested_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "creative_theme": creative_theme,
        "theme_source": theme_source,
        "custom_creative_prompt": custom_creative_prompt,
        "creative_direction": creative_direction,
        "generated_image_key": generated_image_key,
        "image_generation_status": image_generation_status,
        "image_generation_provider": image_generation_provider,
        "image_generation_error": image_generation_error,
        "image_generated_at": image_generated_at.isoformat() if image_generated_at else None,
        "source_image_processed_key": source_image_processed_key,
        "background_removal_status": background_removal_status,
        "background_removal_provider": background_removal_provider,
        "background_removal_error": background_removal_error,
        "background_removal_completed_at": background_removal_completed_at.isoformat() if background_removal_completed_at else None,
        "reference_image_selection": reference_image_selection,
        "image_generation_used_reference": bool(image_generation_used_reference),
        "image_generation_reference_note": image_generation_reference_note,
        "image_prompt": image_prompt,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "content": _content_rows_to_dict(content_rows),
    }


def list_campaigns(conn, tenant_id: str, limit: int = DEFAULT_LIMIT, offset: int = 0, search: Optional[str] = None) -> dict:
    where, params = "WHERE tenant_id = %s", [tenant_id]
    if search:
        where += " AND (campaign_brief ILIKE %s OR source_text ILIKE %s)"
        like = "%" + search.replace("%", r"\%").replace("_", r"\_") + "%"
        params += [like, like]
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM campaigns {where};", params)
        total = cursor.fetchone()[0]

        cursor.execute(
            f"""
            SELECT campaign_id, product_id, campaign_brief, status, input_source, strategy_type,
                   positioning_label, creative_theme, requested_at, completed_at,
                   generated_image_key, image_generation_status, updated_at
            FROM campaigns
            {where}
            ORDER BY requested_at DESC
            LIMIT %s OFFSET %s;
            """,
            (*params, limit, offset),
        )
        rows = cursor.fetchall()

    campaigns = [
        {
            "campaign_id": str(cid),
            "product_id": str(product_id) if product_id else None,
            "campaign_brief": campaign_title(campaign_brief),
            "status": status,
            "input_source": input_source,
            "strategy_type": strategy_type,
            "positioning_label": positioning_label,
            "creative_theme": creative_theme,
            "requested_at": requested_at.isoformat() if requested_at else None,
            "completed_at": completed_at.isoformat() if completed_at else None,
            "has_image": bool(image_key) and image_status == "COMPLETED",
            "generated_image_key": image_key if image_status == "COMPLETED" else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }
        for (cid, product_id, campaign_brief, status, input_source, strategy_type, positioning_label, creative_theme,
             requested_at, completed_at, image_key, image_status, updated_at) in rows
    ]
    return {"campaigns": campaigns, "total": int(total), "limit": limit, "offset": offset}


def find_by_request_key(conn, tenant_id: str, request_key: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT campaign_id FROM campaigns WHERE tenant_id = %s AND request_key = %s;", (tenant_id, request_key))
        row = cursor.fetchone()
    return str(row[0]) if row else None


EDITABLE_VARIANT_FIELDS = ("headline", "body_copy", "hashtags", "cta")


def update_campaign_copy(conn, tenant_id: str, campaign_id: str, *, title: Optional[str] = None,
                         audience_summary: Optional[str] = None, variants: Optional[list] = None) -> bool:
    """Saves the owner's edits. False when the campaign doesn't exist;
    ValueError for a variant the campaign doesn't have."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM campaigns WHERE tenant_id = %s AND campaign_id = %s FOR UPDATE;", (tenant_id, campaign_id))
        if cursor.fetchone() is None:
            return False
        for variant in variants or []:
            fields = {k: variant[k] for k in EDITABLE_VARIANT_FIELDS if k in variant}
            if not fields:
                continue
            sets = ", ".join(f"{k} = %s" for k in fields)
            cursor.execute(
                f"UPDATE campaign_content SET {sets} WHERE tenant_id = %s AND campaign_id = %s AND platform = %s AND variant_index = %s;",
                (*fields.values(), tenant_id, campaign_id, variant["platform"], variant["variant_index"]),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"No {variant['platform']} variant {variant['variant_index']} in this campaign.")
        updates, values = ["updated_at = CURRENT_TIMESTAMP"], []
        if title is not None:
            updates.append("campaign_brief = %s")
            values.append(title)
        if audience_summary is not None:
            updates.append("audience_summary = %s")
            values.append(audience_summary)
        cursor.execute(f"UPDATE campaigns SET {', '.join(updates)} WHERE tenant_id = %s AND campaign_id = %s;",
                       (*values, tenant_id, campaign_id))
    return True


def stored_image_keys(conn, tenant_id: str, campaign_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT source_image_key, source_image_processed_key, generated_image_key FROM campaigns WHERE tenant_id = %s AND campaign_id = %s;",
            (tenant_id, campaign_id),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {"source": row[0], "processed": row[1], "generated": row[2]}


def delete_campaign(conn, tenant_id: str, campaign_id: str) -> bool:
    """Deletes the campaign and its copy (campaign_content cascades)."""
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM campaigns WHERE tenant_id = %s AND campaign_id = %s RETURNING campaign_id;", (tenant_id, campaign_id))
        return cursor.fetchone() is not None
