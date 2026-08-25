from __future__ import annotations

from dungeon_master.models import CampaignDangerProfile, CampaignGenre, CampaignSeed

GENRE_LABELS: dict[CampaignGenre, str] = {
    CampaignGenre.HIGH_FANTASY: "high fantasy",
    CampaignGenre.LOW_FANTASY: "low fantasy",
    CampaignGenre.SWORD_AND_SORCERY: "sword and sorcery",
    CampaignGenre.DARK_FANTASY: "dark fantasy",
    CampaignGenre.GOTHIC_HORROR: "gothic horror",
    CampaignGenre.COSMIC_HORROR: "cosmic horror",
    CampaignGenre.WEIRD_FICTION: "weird fiction",
    CampaignGenre.FAIRY_TALE: "fairy tale",
    CampaignGenre.MYTHIC: "mythic fantasy",
    CampaignGenre.POST_APOCALYPTIC: "post-apocalyptic",
    CampaignGenre.SCIENCE_FANTASY: "science fantasy",
    CampaignGenre.HISTORICAL_FANTASY: "historical fantasy",
    CampaignGenre.URBAN_FANTASY: "urban fantasy",
    CampaignGenre.HEARTH_AND_HOMESTEAD: "hearth and homestead",
}


def render_creative_direction(seed: CampaignSeed) -> str:
    genres = ", ".join(GENRE_LABELS[genre] for genre in seed.genres)
    era = seed.time_period.value.replace("_", " ")
    tech = seed.tech_level.value.replace("_", " ")
    magic = seed.magic_level.value.replace("_", " ")
    stakes = seed.stakes_scale.value.replace("_", " ")
    lines = [
        f"Preset: {seed.preset}.",
        f"Era/technology: {era} with {tech} technology.",
        (
            f"Tone: {seed.tone_grim_noble.value} on the grim/noble axis and "
            f"{seed.tone_dark_bright.value} on the dark/bright axis."
        ),
        f"Genre: {genres}. Magic: {magic}. Stakes: {stakes}.",
    ]
    if seed.inspirations.strip():
        lines.append(f"Inspirations for flavor only: {seed.inspirations.strip()}.")
    if seed.restrictions.strip():
        lines.append(f"Restrictions: {seed.restrictions.strip()}.")
    return "\n".join(f"- {line}" for line in lines)


def render_danger_guidance(danger_profile: CampaignDangerProfile) -> str:
    shared = (
        "Cairn combat uses automatic damage, armor 0-3, HP before STR overflow, "
        "Critical Damage, morale, retreat, and fictional preparation."
    )
    if danger_profile == CampaignDangerProfile.STORY:
        detail = (
            "Keep fights survivable: ordinary foes, low counts, quick morale, "
            "and strong telegraphing."
        )
    elif danger_profile == CampaignDangerProfile.HARSH:
        detail = (
            "Use hardier foes and resource pressure more often, but keep retreat "
            "and preparation viable."
        )
    elif danger_profile == CampaignDangerProfile.LETHAL:
        detail = (
            "Allow serious threats and punishing abilities when clearly telegraphed; "
            "poor preparation can be fatal."
        )
    else:
        detail = (
            "Use default Cairn scale: average foes around 3 HP, hardier foes "
            "around 6 HP, serious threats only when telegraphed."
        )
    return f"{shared} {detail}"

