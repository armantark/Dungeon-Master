from dungeon_master.models import (
    NPC,
    CampaignStatus,
    CharacterSheet,
    GameState,
    GameThread,
    InventoryItem,
    OracleTables,
)


def sample_state() -> GameState:
    return GameState(
        current_scene="A generated scene waits for player action.",
        setting_notes="Generated setting notes for tests.",
        player_notes="Generated player notes for tests.",
        npc_roster_version=2,
        campaign_status=CampaignStatus.ACTIVE,
        character=CharacterSheet(
            name="Test Wanderer",
            archetype="Test archetype",
            epithet="A test character under pressure.",
            backstory="Generated player notes for tests.",
            drive="Survive the test harness.",
            flaw="Too synthetic to trust.",
            condition="Bruised but functional.",
            inventory=[
                InventoryItem(name="Test knife", details="Dull but present."),
                InventoryItem(name="Test map", details="Only half wrong."),
            ],
        ),
        threads=[
            GameThread(title="Generated thread one", stakes="Generated stakes one."),
            GameThread(title="Generated thread two", stakes="Generated stakes two."),
            GameThread(title="Generated thread three", stakes="Generated stakes three."),
        ],
        npcs=[
            NPC(name="Generated NPC One", role="Test role", disposition="watchful"),
            NPC(name="Generated NPC Two", role="Test role", disposition="wary"),
        ],
        oracle_tables=OracleTables(
            event_focus=[
                "thread pressure",
                "npc pressure",
                "location pressure",
                "hidden cost",
                "dangerous choice",
                "new omen",
            ],
            event_actions=[
                "betray",
                "conceal",
                "demand",
                "forsake",
                "guard",
                "pursue",
                "shatter",
                "withhold",
            ],
            event_tones=[
                "bitter",
                "cold",
                "desperate",
                "forbidden",
                "hollow",
                "patient",
                "ruined",
                "solemn",
            ],
            event_subjects=[
                "a debt",
                "a witness",
                "a gate",
                "a relic",
                "a road",
                "a wound",
                "an oath",
                "old blood",
            ],
        ),
    )
