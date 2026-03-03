"""PDF export - classic professional business style."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas as _RLCanvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Classic Business Palette (Traditional & Sober)
# ---------------------------------------------------------------------------
C_NAVY_DARK = colors.HexColor("#1E293B")  # Main headers, professional & deep
C_NAVY_LIGHT = colors.HexColor("#334155")  # Sub-headers
C_STEEL = colors.HexColor("#94A3B8")  # Dividers, accents
C_GREY_BODY = colors.HexColor("#334155")  # Main text
C_GREY_META = colors.HexColor("#64748B")  # Metadata / Captions
C_BG_SOFT = colors.HexColor("#F8FAFC")  # Soft background tint for stats
C_WHITE = colors.white
C_LINK = colors.HexColor("#2563EB")  # Standard professional blue link

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
INNER_W = PAGE_W - 2 * MARGIN

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _S() -> dict[str, ParagraphStyle]:
    return {
        # Cover
        "cover_title": ParagraphStyle(
            "CoverTitle",
            fontName="Helvetica-Bold",
            fontSize=26,
            textColor=C_WHITE,
            leading=32,
            spaceAfter=0,
        ),
        "cover_dates": ParagraphStyle(
            "CoverDates",
            fontName="Helvetica",
            fontSize=12,
            textColor=colors.HexColor("#CBD5E1"),
            leading=16,
            spaceAfter=0,
        ),
        "cover_desc": ParagraphStyle(
            "CoverDesc",
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#94A3B8"),
            leading=14,
            spaceAfter=0,
        ),
        "stat_value": ParagraphStyle(
            "StatValue",
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=C_NAVY_DARK,
            alignment=TA_CENTER,
            leading=18,
        ),
        "stat_label": ParagraphStyle(
            "StatLabel",
            fontName="Helvetica",
            fontSize=8,
            textColor=C_GREY_META,
            alignment=TA_CENTER,
            leading=10,
        ),
        # Sections
        "section": ParagraphStyle(
            "Section",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=C_NAVY_DARK,
            spaceBefore=8,
            spaceAfter=2,
        ),
        "day_num": ParagraphStyle(
            "DayNum",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=C_WHITE,
            leading=14,
            alignment=TA_CENTER,
            opacity=0.8,
        ),
        "day_date": ParagraphStyle(
            "DayDate",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=C_WHITE,
            leading=18,
            alignment=TA_LEFT,
        ),
        # Body
        "item_title": ParagraphStyle(
            "ItemTitle",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=C_NAVY_DARK,
            spaceAfter=1,
            spaceBefore=4,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=10,
            textColor=C_GREY_BODY,
            leading=14,
            spaceAfter=1,
        ),
        "body_indent": ParagraphStyle(
            "BodyIndent",
            fontName="Helvetica",
            fontSize=10,
            textColor=C_GREY_BODY,
            leading=14,
            leftIndent=10,
            spaceAfter=1,
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_GREY_META,
            leading=13,
            spaceAfter=1,
        ),
        "meta_indent": ParagraphStyle(
            "MetaIndent",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_GREY_META,
            leading=13,
            leftIndent=10,
            spaceAfter=1,
        ),
        "link": ParagraphStyle(
            "Link",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_LINK,
            leading=13,
            spaceAfter=1,
        ),
        "link_indent": ParagraphStyle(
            "LinkIndent",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_LINK,
            leading=13,
            leftIndent=10,
            spaceAfter=1,
        ),
        "badge": ParagraphStyle(
            "Badge",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=C_WHITE,
            alignment=TA_CENTER,
        ),
        "act_section": ParagraphStyle(
            "ActSection",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=C_NAVY_LIGHT,
            leading=12,
            spaceBefore=4,
            spaceAfter=2,
            letterSpacing=1,
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hr_steel(thickness: float = 0.8) -> HRFlowable:
    return HRFlowable(
        width="100%",
        thickness=thickness,
        color=C_STEEL,
        spaceBefore=3,
        spaceAfter=3,
    )


def _hr_grey(thickness: float = 0.4) -> HRFlowable:
    return HRFlowable(
        width="100%",
        thickness=thickness,
        color=colors.HexColor("#E2E8F0"),
        spaceBefore=2,
        spaceAfter=2,
    )


def _link_para(label: str, url: str | None, style: ParagraphStyle) -> Paragraph | None:
    if not url:
        return None
    safe = url.replace("&", "&amp;")
    return Paragraph(f'<a href="{safe}" color="#2563EB"><u>{label}</u></a>', style)


def _format_price(price: float | None) -> str:
    if price is None:
        return ""
    return f"{price:,.2f} EUR"


def _format_date_long(d: Any) -> str:
    if not d:
        return "Date TBC"
    if hasattr(d, "weekday"):
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        months = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        return f"{days[d.weekday()]}, {months[d.month - 1]} {d.day}, {d.year}"
    return str(d)


# --- Type badge (Sober tones) ---
_ITEM_TYPES: list[tuple[list[str], str, str]] = [
    (["vuelo", "flight", "avion", "billete", "air"], "FLIGHT", "#334155"),
    (["tren", "train", "ave", "renfe", "rail"], "TRAIN", "#334155"),
    (["bus", "autobus", "transfer", "shuttle"], "BUS", "#334155"),
    (["coche", "car", "rental", "alquiler"], "CAR", "#334155"),
    (["barco", "ferry", "crucero", "boat", "ship"], "FERRY", "#334155"),
    (["seguro", "insurance", "cobertura"], "INSURANCE", "#475569"),
    (["hotel", "hostal", "alojamiento", "airbnb"], "HOTEL", "#1E293B"),
    (["entrada", "museum", "museu", "parque", "theme park"], "TICKET", "#1E293B"),
    (["restaurante", "restaurant", "cena", "comida", "tapas"], "DINING", "#64748B"),
    (["visa", "pasaporte", "passport"], "DOCS", "#475569"),
]

_ACTIVITY_TYPES: list[tuple[list[str], str, str]] = [
    (["museo", "museum", "galeria", "arte", "art", "gallery"], "MUSEUM", "#1E293B"),
    (["playa", "beach", "mar", "ocean"], "BEACH", "#334155"),
    (["hiking", "senderismo", "montaña", "trail", "trek"], "HIKING", "#334155"),
    (["restaurante", "cena", "dinner", "comida", "tapas"], "DINING", "#475569"),
    (["bar", "copa", "cerveza", "beer", "vino", "wine"], "LEISURE", "#475569"),
    (["catedral", "iglesia", "church", "temple", "mezquita"], "CULTURE", "#1E293B"),
    (["castillo", "palace", "palacio", "fortaleza"], "CULTURE", "#1E293B"),
    (["compras", "shopping", "mercado", "market"], "SHOPPING", "#475569"),
    (["concierto", "teatro", "theatre", "espectaculo"], "EVENTS", "#475569"),
    (["spa", "relax", "masaje", "yoga"], "WELLNESS", "#1E293B"),
    (["tour", "excursion", "guia", "guide"], "TOUR", "#334155"),
    (["aeropuerto", "airport", "tren", "train", "transfer"], "TRANSIT", "#334155"),
]


def _infer_badge(
    name: str, table: list[tuple[list[str], str, str]], fallback_label: str = "ACTIVITY"
) -> tuple[str, str]:
    lower = name.lower()
    for keywords, label, color in table:
        if any(kw in lower for kw in keywords):
            return label, color
    return fallback_label, "#64748B"


def _badge_cell(label: str, bg_hex: str, S: dict[str, ParagraphStyle]) -> Table:
    """A small coloured pill label."""
    t = Table(
        [[Paragraph(label, S["badge"])]],
        colWidths=[22 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


# ---------------------------------------------------------------------------
# Cover block
# ---------------------------------------------------------------------------


def _cover_block(trip: Any, stats: dict[str, Any], S: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = []

    # --- Navy header band ---
    date_str = f"{trip.start_date or '?'}  →  {trip.end_date or '?'}"
    desc = trip.description or ""

    header_content: list[list[Any]] = [
        [Paragraph(trip.name, S["cover_title"])],
        [Paragraph(date_str, S["cover_dates"])],
    ]
    if desc:
        header_content.append([Spacer(1, 4 * mm)])
        header_content.append([Paragraph(desc, S["cover_desc"])])

    header_table = Table(header_content, colWidths=[INNER_W])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_NAVY_DARK),
                ("TOPPADDING", (0, 0), (0, 0), 16),
                ("BOTTOMPADDING", (0, -1), (0, -1), 16),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -2), 4),
            ]
        )
    )
    story.append(header_table)

    # --- Stats bar ---
    total_cost = _format_price(stats.get("total_price") or 0)
    stat_col_w = INNER_W / 4

    def _stat(val: str, lbl: str) -> list[Paragraph]:
        return [Paragraph(val, S["stat_value"]), Paragraph(lbl.upper(), S["stat_label"])]

    stats_data = [
        [
            _stat(str(stats.get("day_count", 0)), "days"),
            _stat(str(stats.get("activity_count", 0)), "activities"),
            _stat(f"{stats.get('total_distance_km') or 0} km", "distance"),
            _stat(total_cost, "estimated total"),
        ]
    ]
    stats_table = Table(stats_data, colWidths=[stat_col_w] * 4)
    stats_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_BG_SOFT),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEAFTER", (0, 0), (2, 0), 0.5, colors.HexColor("#E2E8F0")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (3, 0), 12),
                ("LINEBELOW", (0, 0), (-1, -1), 1, C_STEEL),
            ]
        )
    )
    story.append(stats_table)
    story.append(Spacer(1, 10 * mm))
    return story


# ---------------------------------------------------------------------------
# Day header
# ---------------------------------------------------------------------------


def _day_header(index: int, day: Any, S: dict[str, ParagraphStyle]) -> Table:
    num_str = f"DAY {index:02d}"
    date_str = _format_date_long(day.date)

    t = Table(
        [[Paragraph(num_str, S["day_num"]), Paragraph(date_str, S["day_date"])]],
        colWidths=[20 * mm, INNER_W - 20 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_NAVY_DARK),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                # Day number column: no side padding so it centres cleanly
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#475569")),
            ]
        )
    )
    return t


# ---------------------------------------------------------------------------
# Item blocks
# ---------------------------------------------------------------------------


def _general_item_block(item: Any, S: dict[str, ParagraphStyle]) -> list[Any]:
    label, bg = _infer_badge(item.name, _ITEM_TYPES, "ITEM")
    elems: list[Any] = []

    badge = _badge_cell(label, bg, S)
    name_p = Paragraph(f"<b>{item.name}</b>", S["item_title"])
    row = Table([[badge, name_p]], colWidths=[22 * mm, INNER_W - 22 * mm])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
            ]
        )
    )
    elems.append(row)

    if item.description:
        elems.append(Paragraph(item.description, S["body_indent"]))

    meta: list[str] = []
    if item.reservation_id:
        meta.append(f"Booking ref: {item.reservation_id}")
    if item.price is not None:
        meta.append(_format_price(item.price))
    if item.cancelable is not None:
        meta.append("Cancellable" if item.cancelable else "Non-refundable")
    if meta:
        elems.append(Paragraph(" | ".join(meta), S["meta_indent"]))

    lnk = _link_para("Booking link", item.link, S["link_indent"])
    if lnk:
        elems.append(lnk)
    maps = _link_para("View on Google Maps", item.maps_link, S["link_indent"])
    if maps:
        elems.append(maps)

    elems.append(Spacer(1, 4 * mm))
    return elems


def _hotel_block(day: Any, S: dict[str, ParagraphStyle]) -> list[Any]:
    elems: list[Any] = []
    hotel_name = day.hotel_name or "Accommodation TBC"

    badge = _badge_cell("HOTEL", "#1E293B", S)
    name_p = Paragraph(f"<b>{hotel_name}</b>", S["item_title"])
    row = Table([[badge, name_p]], colWidths=[22 * mm, INNER_W - 22 * mm])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
            ]
        )
    )
    elems.append(row)

    if day.hotel_location:
        elems.append(Paragraph(day.hotel_location, S["meta_indent"]))

    meta: list[str] = []
    if day.hotel_price is not None:
        meta.append(f"{_format_price(day.hotel_price)} / night")
    if day.hotel_reservation_id:
        meta.append(f"Booking ref: {day.hotel_reservation_id}")
    if day.hotel_cancelable is not None:
        meta.append("Cancellable" if day.hotel_cancelable else "Non-refundable")
    if meta:
        elems.append(Paragraph(" | ".join(meta), S["meta_indent"]))

    if day.hotel_description:
        elems.append(Paragraph(day.hotel_description, S["body_indent"]))

    hotel_lnk = _link_para("View hotel", day.hotel_link, S["link_indent"])
    if hotel_lnk:
        elems.append(hotel_lnk)
    hotel_maps = _link_para("View on Google Maps", day.hotel_maps_link, S["link_indent"])
    if hotel_maps:
        elems.append(hotel_maps)

    # Travel info
    travel: list[str] = []
    if day.distance_km is not None:
        travel.append(f"{day.distance_km} km")
    if day.distance_hours or day.distance_minutes:
        t = ""
        if day.distance_hours:
            t += f"{day.distance_hours}h "
        if day.distance_minutes:
            t += f"{day.distance_minutes}m"
        travel.append(t.strip())
    if travel:
        elems.append(Paragraph("Travel: " + " · ".join(travel), S["meta_indent"]))

    elems.append(Spacer(1, 4 * mm))
    return elems


def _activity_block(activity: Any, S: dict[str, ParagraphStyle]) -> list[Any]:
    label, bg = _infer_badge(activity.name, _ACTIVITY_TYPES, "ACTIVITY")
    elems: list[Any] = []

    badge = _badge_cell(label, bg, S)
    name_p = Paragraph(f"<b>{activity.name}</b>", S["item_title"])
    row = Table([[badge, name_p]], colWidths=[22 * mm, INNER_W - 22 * mm])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
            ]
        )
    )
    elems.append(row)

    if activity.location:
        elems.append(Paragraph(activity.location, S["meta_indent"]))
    if activity.description:
        elems.append(Paragraph(activity.description, S["body_indent"]))

    meta: list[str] = []
    if activity.price is not None:
        meta.append(_format_price(activity.price))
    if activity.reservation_id:
        meta.append(f"Booking ref: {activity.reservation_id}")
    if meta:
        elems.append(Paragraph(" | ".join(meta), S["meta_indent"]))

    act_lnk = _link_para("Official page", activity.link, S["link_indent"])
    if act_lnk:
        elems.append(act_lnk)
    act_maps = _link_para("View on Google Maps", activity.maps_link, S["link_indent"])
    if act_maps:
        elems.append(act_maps)

    return elems


# ---------------------------------------------------------------------------
# Destination knowledge block
# ---------------------------------------------------------------------------


def _knowledge_block(knowledge: str, S: dict[str, ParagraphStyle]) -> list[Any]:
    """Render knowledge_general text as labeled paragraphs."""
    elems: list[Any] = [
        KeepTogether(
            [
                Paragraph("DESTINATION OVERVIEW", S["act_section"]),
                _hr_steel(),
            ]
        ),
    ]
    for line in knowledge.splitlines():
        line = line.strip()
        if not line:
            elems.append(Spacer(1, 2 * mm))
            continue
        # Lines with a label pattern like "CURRENCY: ..." or "Moneda: ..."
        if ":" in line:
            colon = line.index(":")
            label = line[:colon].strip()
            rest = line[colon + 1 :].strip()
            if label and rest:
                elems.append(Paragraph(f"<b>{label}:</b> {rest}", S["body"]))
                continue
        elems.append(Paragraph(line, S["body"]))
    elems.append(Spacer(1, 6 * mm))
    return elems


# ---------------------------------------------------------------------------
# Page footer canvas
# ---------------------------------------------------------------------------


class _FooterCanvas(_RLCanvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved)
        for i, state in enumerate(self._saved):
            self.__dict__.update(state)
            self._draw_footer(i + 1, total)
            super().showPage()
        super().save()

    def _draw_footer(self, current: int, total: int) -> None:
        self.saveState()
        self.setStrokeColor(C_STEEL)
        self.setLineWidth(0.5)
        self.line(MARGIN, 12 * mm, PAGE_W - MARGIN, 12 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(C_GREY_META)
        self.drawString(MARGIN, 8 * mm, self._doc_title if hasattr(self, "_doc_title") else "")
        self.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Page {current} of {total}")
        self.restoreState()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_trip_pdf(
    trip: Any,
    ordered_days: list[Any],
    general_items: list[Any],
    stats: dict[str, Any],
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
        title=trip.name,
        author="Trip Planner",
    )

    S = _S()
    story: list[Any] = []

    # Cover
    story.extend(_cover_block(trip, stats, S))

    # General items
    if general_items:
        story.append(
            KeepTogether(
                [
                    Paragraph("TRANSPORT & LOGISTICS OVERVIEW", S["act_section"]),
                    _hr_steel(),
                ]
            )
        )
        for item in general_items:
            story.extend(_general_item_block(item, S))
        story.append(Spacer(1, 4 * mm))

    # Destination knowledge
    knowledge = (trip.knowledge_general or "").strip()
    if knowledge:
        story.extend(_knowledge_block(knowledge, S))

    # Days
    for index, day in enumerate(ordered_days, start=1):
        day_elems: list[Any] = [
            Spacer(1, 6 * mm),
            _day_header(index, day, S),
            Spacer(1, 8 * mm),
        ]

        # Hotel
        day_elems.extend(_hotel_block(day, S))

        # Activities
        if day.activities:
            day_elems.append(Paragraph("DAY ITINERARY", S["act_section"]))
            day_elems.append(_hr_steel(0.5))
            for i, activity in enumerate(day.activities):
                day_elems.extend(_activity_block(activity, S))
                if i < len(day.activities) - 1:
                    day_elems.append(_hr_grey())
            day_elems.append(Spacer(1, 2 * mm))
        else:
            day_elems.append(Paragraph("No activities planned.", S["meta"]))

        story.append(KeepTogether(day_elems[:6]))
        story.extend(day_elems[6:])

    # Build
    try:

        class _TitledCanvas(_FooterCanvas):
            pass

        _TitledCanvas._doc_title = trip.name  # type: ignore[attr-defined]
        doc.build(story, canvasmaker=_TitledCanvas)
    except Exception:
        doc.build(story)

    buffer.seek(0)
    return buffer.getvalue()
