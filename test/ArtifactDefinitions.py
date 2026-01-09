# Define an artifact with multiple requirements
dragonlance = Artifact(
    name="Dragonlance", 
    description="A powerful weapon against dragons",
    bonus={"attack": 3, "vs_dragon_bonus": 5},
    requirements=[
        {"type": "race", "value": "solamnic"},
        {"type": "trait", "value": "is_leader"}
    ]
)

# Or with custom requirements
silver_arm = Artifact(
    name="Silver Arm of Ergoth",
    description="Grants immunity to fear",
    bonus={"fear_immunity": True},
    requirements=[
        {"type": "custom", "value": lambda unit: unit.name == "Sturm"}
    ]
)
