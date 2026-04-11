"""
navigation.py — VJTI Campus Navigation System
Registered as a Flask Blueprint so it plugs into backend_api.py cleanly.

Usage in backend_api.py:
    from navigation import navigation_bp
    app.register_blueprint(navigation_bp)

Endpoints:
    POST /api/navigate          → { "from": "...", "to": "..." }
    GET  /api/navigate/locations → list of all known locations
    GET  /api/navigate/graph     → full node graph (debug)
"""

from flask import Blueprint, request, jsonify

navigation_bp = Blueprint("navigation", __name__)

# ═══════════════════════════════════════════════════════════════════════════════
# LOCATION GRAPH
# Each node represents a physical location.
# Each edge is a walkable connection with a description of how to get there.
#
# Node ID naming convention mirrors the image file names:
#   elec_f1_*  → electrical/civil building, floor 1
#   elec_f2_*  → electrical/civil building, floor 2
#   campus_*   → outdoor / campus-level locations
#
# GROUND TRUTH (from your images and descriptions):
#   - Quadrangle (Quad / Basketball Ground) is the central hub.
#     From Quad you can see BOTH staircases.
#   - Staircase 1 and Staircase 2 connect all 3 floors.
#   - Floor 1 (elec_civil building): rooms 101-106, library, civil seminar hall,
#     examination house, environmental engg lab, civil dept junction.
#   - Floor 2 (elec building): DSP lab, Computer Lab (Civil), Python lab,
#     Data Science lab, NLP lab, Analog Electronics lab,
#     Women Development Cell.
# ═══════════════════════════════════════════════════════════════════════════════

GRAPH = {

    # ── Campus / Outdoor ──────────────────────────────────────────────────────

    "campus_entrance": {
        "label": "VJTI Main Entrance",
        "floor": "ground",
        "image": None,
        "edges": {
            "campus_quad": "Walk straight into the campus. The Quadrangle (Basketball Ground) is ahead of you.",
        }
    },

    "campus_quad": {
        "label": "Quadrangle (Quad / Basketball Ground)",
        "floor": "ground",
        "image": "Quadrangle_or_Quad.jpg",
        "edges": {
            "campus_entrance":         "Walk towards the main gate to reach the campus entrance.",
            "elec_gf_corridor_to_al005_to_machines": "From the Quad, enter the Electrical Department ground floor corridor from the Staircase 2 side.",
            "elec_gf_right_path_from_quad_to_three_way_junction": "From the Quad, move towards the right-side Electrical Department ground floor junction.",
            "elec_f1_staircase_2":     "From the Quad, look towards the Electrical/Civil building. Staircase 2 is on the RIGHT side of the building.",
            "elec_f1_staircase_1":     "From the Quad, look towards the Electrical/Civil building. Staircase 1 is on the LEFT side of the building.",
            "elec_f1_corridor_main":   "Enter the Electrical/Civil building from the Quad. You are now on Floor 1.",
        }
    },

    # ── Electrical Department — Ground Floor (entry from Staircase 2 side) ──

    "elec_gf_entrance_staircase2_side": {
        "label": "Electrical Department Ground Floor — Entrance (Staircase 2 side)",
        "floor": "ground",
        "image": "elec_f1_staircase_2.jpeg",
        "edges": {
            "campus_quad": "Walk out towards the Quadrangle.",
            "elec_f1_staircase_2": "Use Staircase 2 to move up to Floor 1.",
        }
    },

    # "elec_gf_overview": {
    #     "label": "Electrical Department Ground Floor — Overview",
    #     "floor": "ground",
    #     "image": "elec_gf_overview.jpg",
    #     "edges": {
    #         "elec_gf_entrance_staircase2_side": "Move back towards the Staircase 2 side entrance.",
    #         "elec_gf_corridor_to_al005_to_machines": "Proceed into the corridor that leads towards AL005 and Electrical Machines Lab.",
    #     }
    # },

    "elec_gf_corridor_to_al005_to_machines": {
        "label": "Ground Floor Corridor — Towards AL005 to Electrical Machines Lab",
        "floor": "ground",
        "image": "elec_gf_corridor_to_al005_to_machines.jpg",
        "edges": {
            "campus_quad": "Walk out towards the Quadrangle.",
            "elec_gf_entrance_staircase2_side": "Move towards the Staircase 2 side entrance.",
            "elec_gf_room_al005": "AL005 classroom is along this corridor.",
            "elec_gf_lab_vlsi": "Continue further to reach the VLSI lab.",
            "elec_gf_lab_simulation": "Continue along the same side to reach the Simulation lab.",
            "elec_gf_lab_biomedical_research": "Proceed further to the Biomedical Research lab.",
            "elec_gf_lab_electrical_machines": "At the end of this corridor is the Electrical Machines lab.",
        }
    },

    "elec_gf_room_al005": {
        "label": "AL005 Classroom",
        "floor": "ground",
        "image": "elec_gf_room_al005.jpg",
        "edges": {
            "elec_gf_corridor_to_al005_to_machines": "Step back into the corridor.",
            "elec_gf_lab_vlsi": "Continue ahead from AL005 to reach the VLSI lab.",
        }
    },

    "elec_gf_lab_vlsi": {
        "label": "VLSI Lab (Very-Large-Scale Integration)",
        "floor": "ground",
        "image": "elec_gf_lab_vlsi.jpg",
        "edges": {
            "elec_gf_corridor_to_al005_to_machines": "Step back into the main corridor.",
            "elec_gf_room_al005": "AL005 is nearby on this corridor.",
            "elec_gf_lab_simulation": "Continue further to reach the Simulation lab.",
        }
    },

    "elec_gf_lab_simulation": {
        "label": "Simulation Lab",
        "floor": "ground",
        "image": "elec_gf_lab_simulation.jpg",
        "edges": {
            "elec_gf_corridor_to_al005_to_machines": "Step back into the main corridor.",
            "elec_gf_lab_vlsi": "The VLSI lab is just behind you.",
            "elec_gf_lab_biomedical_research": "Continue ahead to the Biomedical Research lab.",
        }
    },

    "elec_gf_lab_biomedical_research": {
        "label": "Biomedical Research Lab",
        "floor": "ground",
        "image": "elec_gf_lab_biomedical_research.jpg",
        "edges": {
            "elec_gf_corridor_to_al005_to_machines": "Step back into the main corridor.",
            "elec_gf_lab_simulation": "Simulation lab is just behind you.",
            "elec_gf_lab_electrical_machines": "Continue to the corridor end for Electrical Machines lab.",
        }
    },

    "elec_gf_lab_electrical_machines": {
        "label": "Electrical Machines Lab",
        "floor": "ground",
        "image": "elec_gf_lab_electrical_machines.jpg",
        "edges": {
            "elec_gf_corridor_to_al005_to_machines": "Step back into the corridor.",
            "elec_gf_lab_biomedical_research": "Biomedical Research lab is nearby.",
        }
    },

    # ── Electrical Department — Ground Floor Right Side (from Quad) ─────────

    "elec_gf_right_path_from_quad_to_three_way_junction": {
        "label": "Ground Floor Right Side — Three-Way Junction",
        "floor": "ground",
        "image": "elec_gf_right_path_from_quad_to_three_way_junction.jpg",
        "edges": {
            "campus_quad": "Walk back towards the Quadrangle.",
            "elec_gf_right_hallway_towards_study_space": "Take the hallway towards the study space.",
            "elec_gf_right_hallway_towards_electrical_board": "Take the hallway towards the Electrical Department board side.",
            "elec_gf_right_hallway_towards_f1_staircase": "Take the corridor that leads to the staircase to Floor 1.",
        }
    },

    "elec_gf_right_hallway_towards_study_space": {
        "label": "Ground Floor Hallway — Towards Study Space",
        "floor": "ground",
        "image": "elec_gf_right_hallway_towards_study_space.jpeg",
        "edges": {
            "elec_gf_right_path_from_quad_to_three_way_junction": "Return to the three-way junction.",
            "elec_gf_right_study_space": "The large Study Space room is on this hallway.",
        }
    },

    "elec_gf_right_study_space": {
        "label": "Study Space (Large Room)",
        "floor": "ground",
        "image": "elec_gf_right_study_space.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_study_space": "Step back into the hallway towards the three-way junction.",
        }
    },

    "elec_gf_right_hallway_towards_electrical_board": {
        "label": "Ground Floor Hallway — Towards Electrical Department Board",
        "floor": "ground",
        "image": "elec_gf_right_hallway_towards_electrical_board.jpeg",
        "edges": {
            "elec_gf_right_path_from_quad_to_three_way_junction": "Return to the three-way junction.",
            "elec_gf_right_room_al002": "AL002 is on this hallway.",
            "elec_gf_right_room_al003": "AL003 is on this hallway.",
            "elec_gf_right_vjti_tbi": "VJTI TBI is on this hallway.",
            "elec_gf_right_lab_emc2": "EMC square lab is on this hallway.",
            "elec_gf_right_electrical_dept_board_staircase": "Continue till the end to reach the Electrical Department board and staircase.",
        }
    },

    "elec_gf_right_hallway_towards_f1_staircase": {
        "label": "Ground Floor Hallway — Towards Staircase to Floor 1",
        "floor": "ground",
        "image": "elec_gf_right_hallway_towards_f1_staircase.jpeg",
        "edges": {
            "elec_gf_right_path_from_quad_to_three_way_junction": "Return to the three-way junction.",
            "elec_gf_right_electrical_dept_board_staircase": "This corridor meets the staircase/end-board area.",
        }
    },

    "elec_gf_right_room_al002": {
        "label": "AL002 Classroom",
        "floor": "ground",
        "image": "elec_gf_right_room_al002.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_electrical_board": "Step back into the hallway.",
        }
    },

    "elec_gf_right_room_al003": {
        "label": "AL003 Classroom",
        "floor": "ground",
        "image": "elec_gf_right_room_al003.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_electrical_board": "Step back into the hallway.",
        }
    },

    "elec_gf_right_vjti_tbi": {
        "label": "VJTI TBI",
        "floor": "ground",
        "image": "elec_gf_right_vjti_tbi.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_electrical_board": "Step back into the hallway.",
        }
    },

    "elec_gf_right_lab_emc2": {
        "label": "EMC Square Lab",
        "floor": "ground",
        "image": "elec_gf_right_lab_emc2.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_electrical_board": "Step back into the hallway.",
        }
    },

    "elec_gf_right_electrical_dept_board_staircase": {
        "label": "Electrical Department Board & Staircase to Floor 1",
        "floor": "ground",
        "image": "elec_gf_right_electrical_dept_board_staircase.jpg",
        "edges": {
            "elec_gf_right_hallway_towards_electrical_board": "Walk back along the hallway.",
            "elec_gf_right_hallway_towards_f1_staircase": "Walk back towards the three-way junction corridor.",
        }
    },

    # ── Electrical/Civil Building — Staircases ────────────────────────────────

    "elec_f1_staircase_1": {
        "label": "Staircase 1 (Left side of building)",
        "floor": 1,
        "image": "elec_f1_staircase_1.jpeg",
        "edges": {
    "campus_quad": "Go down and out to reach the Quadrangle.",
    "elec_f1_corridor_main": "From Staircase 1, enter the corridor to access Floor 1.",
    "elec_f2_staircase_1": "Climb up one floor to reach Floor 2 via Staircase 1.",
    "elec_f1_room_at105_door": "Room 105 is on the Staircase 1 side corridor.",
    "elec_f1_junction_at106_civil_dept": "The Civil Department junction is on the Staircase 1 side.",
    "elec_f1_examination_house_entrance": "Examination House is on the Staircase 1 side corridor.",
    "elec_f1_lab_environmental_engg_door": "Environmental Engineering Lab is near the Examination House side."
}
    },

    "elec_f2_staircase_1": {
        "label": "Staircase 1 — Floor 2 landing",
        "floor": 2,
        "image": "elec_f2_staircase_1.jpeg",
        "edges": {
            "elec_f1_staircase_1":   "Go down one floor to reach Floor 1 via Staircase 1.",
            "elec_f3_staircase_1":   "Climb up one more floor to reach Floor 3 via Staircase 1.",
            "elec_f2_corridor_main": "Enter the Floor 2 corridor from this staircase landing.",
        }
    },

    "elec_f3_staircase_1": {
        "label": "Staircase 1 — Floor 3 landing",
        "floor": 3,
        "image": None,
        "edges": {
            "elec_f2_staircase_1": "Go down one floor to reach Floor 2 via Staircase 1.",
            "elec_f3_corridor_main": "Enter the Floor 3 corridor from this staircase landing.",
        }
    },

    "elec_f1_staircase_2": {
        "label": "Staircase 2 (Right side of building)",
        "floor": 1,
        "image": "elec_f1_staircase_2.jpeg",
        "edges": {
    "campus_quad": "Go down and out to reach the Quadrangle.",
    "elec_gf_entrance_staircase2_side": "Go down towards the Electrical ground floor entrance on the Staircase 2 side.",
    "elec_f1_corridor_main": "From Staircase 2, enter the corridor to access Floor 1.",
    "elec_f2_staircase_2": "Climb up one floor to reach Floor 2 via Staircase 2.",
    "elec_f1_room_al101_door": "AL101 is on the Staircase 2 side corridor.",
    "elec_f1_library_entrance": "Library is on the Staircase 2 side corridor.",
    "elec_f1_corridor_al_facing_library": "Proceed toward the library-side corridor viewpoint.",
}
    },

    "elec_f2_staircase_2": {
        "label": "Staircase 2 — Floor 2 landing",
        "floor": 2,
        "image": "elec_f2_staircase_2.jpeg",
        "edges": {
            "elec_f1_staircase_2":   "Go down one floor to reach Floor 1 via Staircase 2.",
            "elec_f3_staircase_2":   "Climb up one more floor to reach Floor 3 via Staircase 2.",
            "elec_f2_corridor_main": "Enter the Floor 2 corridor from this staircase landing.",
            "elec_f2_corridor_main_facing_dsp_lab": "DSP Lab is on the middle of the corridor.",
            "elec_f2_junction_at_computer_civil_lab": "Computer/Python/DS/NLP labs are along this corridor stretch from Staircase 2.",
            "elec_f2_junction_women_development_cell_staircase": "Women Development Cell junction is right next to Staircase 2.",
            "elec_f2_lab_data_science_door": "Data Science Lab is on the Staircase 2 side corridor on Floor 2.",
        }
    },

    "elec_f3_staircase_2": {
        "label": "Staircase 2 — Floor 3 landing",
        "floor": 3,
        "image": None,
        "edges": {
            "elec_f2_staircase_2":   "Go down one floor to reach Floor 2 via Staircase 2.",
            "elec_f3_corridor_main": "Enter the Floor 3 corridor from this staircase landing.",
        }
    },

    # ── Floor 1 — Main Corridor ───────────────────────────────────────────────

    "elec_f1_corridor_main": {
        "label": "Floor 1 — Main Corridor",
        "floor": 1,
        "image": "elec_civil_f1_corridor_al_facing_al102.jpg",
        "edges": {
            "elec_f1_staircase_2":              "Walk to the right end of the corridor to reach Staircase 2.",
            "elec_f1_staircase_1":              "Walk to the left end of the corridor to reach Staircase 1.",
            "elec_f1_room_al101_door":          "Room 101 is the first door on your right as you enter the corridor.",
            "elec_f1_room_at105_door":          "Walk along the corridor. Room 105 is further ahead on the right.",
            "elec_f1_junction_at106_civil_dept":"Continue along the corridor to reach the junction at Room 106 / Civil Dept.",
            "elec_f1_library_entrance":         "The library entrance is along the right side of the corridor.",
            "elec_f1_corridor_al_facing_library":"Turn and walk towards the library end of the corridor.",
        }
    },

    "elec_f1_corridor_al_facing_library": {
        "label": "Floor 1 Corridor — Facing Library",
        "floor": 1,
        "image": "elec_civil_f1_corridor_al_facing_library.jpg",
        "edges": {
            "elec_f1_corridor_main":    "Turn around to face the main corridor direction.",
            "elec_f1_library_entrance": "The library entrance is directly ahead of you.",
            "elec_f1_corridor_at_facing_examhouse": "Turn around to face AL102 , walk till end to find examination house on the left.",
        }
    },

    "elec_f1_corridor_at_facing_examhouse": {
        "label": "Floor 1 Corridor — Facing Examination House",
        "floor": 1,
        "image": "elec_civil_f1_corridor_at_facing_examhouse.jpg",
        "edges": {
            "elec_f1_corridor_al_facing_library":  "Turn around and walk towards the farther staircases to find the library at the end.",
            "elec_f1_examination_house_entrance":  "The Examination House entrance is directly ahead.",
            "elec_f1_lab_environmental_engg_door": "The Environmental Engineering Lab door is on this stretch of corridor.",
        }
    },

    # ── Floor 1 — Rooms & Labs ────────────────────────────────────────────────

    "elec_f1_room_al101_door": {
        "label": "Room 101 — Door",
        "floor": 1,
        "image": "elec_civil_f1_room_al101_door.jpg",
        "edges": {
            "elec_f1_corridor_main": "Step back into the main corridor.",
            "elec_f1_room_at105_door": "Walk further along the corridor to reach Room 105.",
            "elec_f1_staircase_2": "Staircase 2 is at the end of the corridor on this side.",
        }
    },

    "elec_f1_room_at105_door": {
        "label": "Room 105 — Door",
        "floor": 1,
        "image": "elec_civil_f1_room_at105_door.jpg",
        "edges": {
            "elec_f1_corridor_main":            "Step back into the main corridor.",
            "elec_f1_room_al101_door":          "Walk back along the corridor to reach Room 101.",
            "elec_f1_junction_at106_civil_dept":"Continue ahead to the junction at Room 106 / Civil Dept.",
            "elec_f1_staircase_1": "Staircase 1 is at the start of the corridor on this side.",
        }
    },

    "elec_f1_junction_at106_civil_dept": {
        "label": "Junction at Room 106 / Civil Department",
        "floor": 1,
        "image": "elec_civil_f1_junction_at106_civil_dept.jpg",
        "edges": {
            "elec_f1_corridor_main":       "Walk back along the main corridor.",
            "elec_f1_room_at105_door":     "Room 105 is behind you along the corridor.",
            "elec_f1_civil_seminar_hall_door": "The Civil Seminar Hall door is at this junction.",
            "elec_f1_corridor_al_facing_library": "Turn towards the library direction from this junction.",
            "elec_f1_staircase_1": "Staircase 1 is at the start of the corridor on this side.",
        }
    },

    "elec_f1_civil_seminar_hall_door": {
        "label": "Civil Seminar Hall — Door",
        "floor": 1,
        "image": "elec_civil_f1_civil_seminar_hall_door.jpg",
        "edges": {
            "elec_f1_junction_at106_civil_dept": "Step back to the junction at Room 106.",
            "elec_f1_corridor_main":             "Walk back to the main corridor.",
        }
    },

    "elec_f1_library_entrance": {
        "label": "Library Entrance",
        "floor": 1,
        "image": "elec_civil_f1_library_entrance.jpg",
        "edges": {
            "elec_f1_corridor_al_facing_library": "Step back into the corridor facing the library direction.",
            "elec_f1_corridor_main":              "Walk back to the main corridor.",
            "elec_f1_staircase_2": "Staircase 2 is at the start of the corridor on this side.",
        }
    },

    "elec_f1_examination_house_entrance": {
        "label": "Examination House Entrance",
        "floor": 1,
        "image": "elec_civil_f1_examination_house_entrance.jpg",
        "edges": {
            "elec_f1_corridor_at_facing_examhouse": "Step back into the corridor.",
            "elec_f1_lab_environmental_engg_door":  "The Environmental Engg Lab is nearby on the same corridor stretch.",
            "elec_f1_staircase_1": "Staircase 1 is at the start of the corridor on this side.",
        }
    },

    "elec_f1_lab_environmental_engg_door": {
        "label": "Environmental Engineering Lab — Door",
        "floor": 1,
        "image": "elec_civil_f1_lab_environmental_engg_door.jpg",
        "edges": {
            "elec_f1_corridor_at_facing_examhouse": "Step back into the corridor.",
            "elec_f1_examination_house_entrance":   "The Examination House is nearby.",
            "elec_f1_staircase_1": "Staircase 1 is at the start of the corridor on this side.",
        }
    },

    # ── Floor 2 — Main Corridor ───────────────────────────────────────────────

    "elec_f2_corridor_main": {
        "label": "Floor 2 — Main Corridor",
        "floor": 2,
        "image": "elec_f2_corridor_main_facing_dsp_lab.jpg",
        "edges": {
            "elec_f2_staircase_2":                   "Walk to the right end of the corridor to reach Staircase 2.",
            "elec_f2_staircase_1":                   "Walk to the left end of the corridor to reach Staircase 1.",
            "elec_f2_lab_dsp_door":                  "The DSP Lab door is visible along the corridor on the right side.",
            "elec_f2_junction_at_computer_civil_lab": "Walk further along the corridor to reach the junction at the Computer Civil Lab.",
            "elec_f2_junction_women_development_cell_staircase": "Walk to the end of the corridor to reach the Women Development Cell / staircase junction.",
        }
    },

    # ── Floor 2 — Labs & Rooms ────────────────────────────────────────────────

    "elec_f2_lab_dsp_door": {
        "label": "Digital Signal Processing (DSP) Lab — Door",
        "floor": 2,
        "image": "elec_f2_lab_dsp_door.jpg",
        "edges": {
            "elec_f2_corridor_main":                  "Step back into the main Floor 2 corridor.",
            "elec_f2_junction_at_computer_civil_lab": "Continue along the corridor towards the Computer Civil Lab junction.",
            "elec_f2_staircase_2": "Staircase 2 is at the start of the corridor on this side.",
        }
    },

    "elec_f2_junction_at_computer_civil_lab": {
        "label": "Junction at Computer Lab (Civil) — leads to Python, Data Science & NLP Labs",
        "floor": 2,
        "image": "elec_f2_junction_at_computer_civil_lab_facing_python_ds_nlp_labs.jpg",
        "edges": {
            "elec_f2_corridor_main":    "Walk back along the corridor towards the main corridor / staircases.",
            "elec_f2_lab_dsp_door":     "The DSP Lab is behind you along the corridor.",
            "elec_f2_lab_computer_civil_door": "The Computer Lab (Civil) door is immediately to your left at this junction.",
            "elec_f2_lab_python_door":  "Continue straight ahead through the open double doors to reach the Python Lab.",
            "elec_f2_lab_data_science_door": "Continue ahead past the Computer Civil Lab to reach the Data Science Lab.",
            "elec_f2_lab_nlp_door":     "Continue ahead — the NLP Lab is further down from the Data Science Lab.",
            "elec_f2_staircase_2": "Staircase 2 is at the end of the corridor on this side.",
        }
    },

    "elec_f2_lab_computer_civil_door": {
        "label": "Computer Laboratory (Civil) — Door",
        "floor": 2,
        "image": "elec_f2_lab_computer_civil_door.jpg",
        "edges": {
            "elec_f2_junction_at_computer_civil_lab": "Step back to the junction.",
            "elec_f2_corridor_main":                  "Walk back to the main corridor.",
        }
    },

    "elec_f2_lab_python_door": {
        "label": "Python Lab — Door",
        "floor": 2,
        "image": None,
        "edges": {
            "elec_f2_junction_at_computer_civil_lab": "Step back to the junction at the Computer Civil Lab.",
            "elec_f2_lab_data_science_door":          "The Data Science Lab is nearby.",
        }
    },

    "elec_f2_lab_data_science_door": {
        "label": "Data Science Lab — Door",
        "floor": 2,
        "image": None,
        "edges": {
            "elec_f2_junction_at_computer_civil_lab": "Step back to the junction.",
            "elec_f2_lab_python_door":  "The Python Lab is nearby.",
            "elec_f2_lab_nlp_door":     "The NLP Lab is further along.",
        }
    },

    "elec_f2_lab_nlp_door": {
        "label": "NLP Lab — Door",
        "floor": 2,
        "image": None,
        "edges": {
            "elec_f2_junction_at_computer_civil_lab": "Step back to the junction.",
            "elec_f2_lab_data_science_door":          "The Data Science Lab is nearby.",
            "elec_f2_staircase_2": "Staircase 2 is at the end of the corridor on this side.",
        }
    },

    "elec_f2_lab_analog_electronics_door": {
        "label": "Analog Electronics Lab — Door",
        "floor": 2,
        "image": None,
        "edges": {
            "elec_f2_junction_women_development_cell_staircase": "The Analog Electronics Lab is just to the right of the Women Development Cell junction.",
            "elec_f2_corridor_main": "Walk back along the corridor.",
        }
    },

    "elec_f2_junction_women_development_cell_staircase": {
        "label": "Junction — Women Development Cell & Staircase",
        "floor": 2,
        "image": "elec_f2_junction_women_development_cell_staircase.jpg",
        "edges": {
            "elec_f2_corridor_main":              "Walk back along the Floor 2 corridor.",
            "elec_f2_lab_analog_electronics_door":"The Analog Electronics Lab is to the right of this junction.",
            "elec_f2_staircase_2":                "Staircase 2 is accessible from this end of the corridor.",
        }
    },

    # ── Floor 3 ───────────────────────────────────────────────────────────────
    # Placeholder — add room/lab nodes here as you photograph Floor 3

    "elec_f3_corridor_main": {
        "label": "Floor 3 — Main Corridor",
        "floor": 3,
        "image": None,
        "edges": {
            "elec_f3_staircase_1": "Walk to the left end to reach Staircase 1.",
            "elec_f3_staircase_2": "Walk to the right end to reach Staircase 2.",
        }
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# ALIASES
# Maps natural language names → canonical node IDs.
# This is what lets the chatbot understand "dsp lab", "python lab",
# "quad", "ground floor library", etc. without needing exact node IDs.
# ═══════════════════════════════════════════════════════════════════════════════

ALIASES = {
    # Campus / Outdoor
    "entrance":               "campus_entrance",
    "main entrance":          "campus_entrance",
    "gate":                   "campus_entrance",
    "main gate":              "campus_entrance",
    "quad":                   "campus_quad",
    "quadrangle":             "campus_quad",
    "basketball ground":      "campus_quad",
    "basketball court":       "campus_quad",
    "ground":                 "campus_quad",

    # Electrical Department Ground Floor
    "electrical ground floor": "elec_gf_corridor_to_al005_to_machines",
    "electrical department ground floor": "elec_gf_corridor_to_al005_to_machines",
    "ground floor electrical": "elec_gf_corridor_to_al005_to_machines",
    "ground floor overview": "elec_gf_corridor_to_al005_to_machines",
    "electrical ground floor entrance": "elec_gf_entrance_staircase2_side",
    "staircase 2 side entrance": "elec_gf_entrance_staircase2_side",
    "al005": "elec_gf_room_al005",
    "al 005": "elec_gf_room_al005",
    "al005 room": "elec_gf_room_al005",
    "al 005 room": "elec_gf_room_al005",
    "al005 classroom": "elec_gf_room_al005",
    "vlsi lab": "elec_gf_lab_vlsi",
    "very large scale integration lab": "elec_gf_lab_vlsi",
    "very-large-scale integration lab": "elec_gf_lab_vlsi",
    "simulation lab": "elec_gf_lab_simulation",
    "biomedical research lab": "elec_gf_lab_biomedical_research",
    "biomedical lab": "elec_gf_lab_biomedical_research",
    "research lab": "elec_gf_lab_biomedical_research",
    "electrical machines lab": "elec_gf_lab_electrical_machines",
    "machines lab": "elec_gf_lab_electrical_machines",

    # Electrical Department Ground Floor Right Side (overview image intentionally omitted)
    "right side ground floor": "elec_gf_right_path_from_quad_to_three_way_junction",
    "right side electrical ground floor": "elec_gf_right_path_from_quad_to_three_way_junction",
    "three way junction": "elec_gf_right_path_from_quad_to_three_way_junction",
    "study space hallway": "elec_gf_right_hallway_towards_study_space",
    "hallway towards study space": "elec_gf_right_hallway_towards_study_space",
    "study space": "elec_gf_right_study_space",
    "large room": "elec_gf_right_study_space",
    "large study space": "elec_gf_right_study_space",
    "study room": "elec_gf_right_study_space",
    "hallway towards electrical board": "elec_gf_right_hallway_towards_electrical_board",
    "electrical board hallway": "elec_gf_right_hallway_towards_electrical_board",
    "hallway to first floor staircase": "elec_gf_right_hallway_towards_f1_staircase",
    "al002": "elec_gf_right_room_al002",
    "al 002": "elec_gf_right_room_al002",
    "room al002": "elec_gf_right_room_al002",
    "al003": "elec_gf_right_room_al003",
    "al 003": "elec_gf_right_room_al003",
    "room al003": "elec_gf_right_room_al003",
    "vjti tbi": "elec_gf_right_vjti_tbi",
    "tbi": "elec_gf_right_vjti_tbi",
    "emc2": "elec_gf_right_lab_emc2",
    "emc 2": "elec_gf_right_lab_emc2",
    "emc square": "elec_gf_right_lab_emc2",
    "emc square lab": "elec_gf_right_lab_emc2",
    "emc^2 lab": "elec_gf_right_lab_emc2",
    "electrical department board": "elec_gf_right_electrical_dept_board_staircase",
    "board and staircase": "elec_gf_right_electrical_dept_board_staircase",

    # Staircases
    "staircase":              "elec_f1_staircase_1",
    "stairs":                 "elec_f1_staircase_1",
    "staircase 1":            "elec_f1_staircase_1",
    "staircase 2":            "elec_f1_staircase_2",

    # Floor 1
    "floor 1":                "elec_f1_corridor_main",
    "f1":                     "elec_f1_corridor_main",
    "ground floor":           "elec_f1_corridor_main",
    "first floor":            "elec_f1_corridor_main",
    "room 101":               "elec_f1_room_al101_door",
    "al101":                  "elec_f1_room_al101_door",
    "room 105":               "elec_f1_room_at105_door",
    "at105":                  "elec_f1_room_at105_door",
    "room 106":               "elec_f1_junction_at106_civil_dept",
    "civil department":       "elec_f1_junction_at106_civil_dept",
    "civil dept":             "elec_f1_junction_at106_civil_dept",
    "civil seminar hall":     "elec_f1_civil_seminar_hall_door",
    "seminar hall":           "elec_f1_civil_seminar_hall_door",
    "library":                "elec_f1_library_entrance",
    "examination house":      "elec_f1_examination_house_entrance",
    "exam house":             "elec_f1_examination_house_entrance",
    "environmental lab":      "elec_f1_lab_environmental_engg_door",
    "environmental engg lab": "elec_f1_lab_environmental_engg_door",
    "environmental engineering lab": "elec_f1_lab_environmental_engg_door",

    # Floor 2
    "floor 2":                "elec_f2_corridor_main",
    "f2":                     "elec_f2_corridor_main",
    "second floor":           "elec_f2_corridor_main",
    "dsp lab":                "elec_f2_lab_dsp_door",
    "digital signal processing lab": "elec_f2_lab_dsp_door",
    "digital signal processing": "elec_f2_lab_dsp_door",
    "computer lab civil":     "elec_f2_lab_computer_civil_door",
    "computer laboratory civil": "elec_f2_lab_computer_civil_door",
    "civil computer lab":     "elec_f2_lab_computer_civil_door",
    "python lab":             "elec_f2_lab_python_door",
    "data science lab":       "elec_f2_lab_data_science_door",
    "ds lab":                 "elec_f2_lab_data_science_door",
    "nlp lab":                "elec_f2_lab_nlp_door",
    "natural language processing lab": "elec_f2_lab_nlp_door",
    "analog electronics lab": "elec_f2_lab_analog_electronics_door",
    "analog lab":             "elec_f2_lab_analog_electronics_door",
    "women development cell": "elec_f2_junction_women_development_cell_staircase",
    "women cell":             "elec_f2_junction_women_development_cell_staircase",
    "wdc":                    "elec_f2_junction_women_development_cell_staircase",

    # Floor 3
    "floor 3":                "elec_f3_corridor_main",
    "f3":                     "elec_f3_corridor_main",
    "third floor":            "elec_f3_corridor_main",
}


# ═══════════════════════════════════════════════════════════════════════════════
# BFS PATHFINDING
# Finds the shortest path between two nodes in the graph.
# Returns a list of node IDs representing the route.
# ═══════════════════════════════════════════════════════════════════════════════

def _bfs(start: str, end: str) -> "list[str] | None":
    """Breadth-first search. Returns ordered list of node IDs or None."""
    if start == end:
        return [start]
    visited  = {start}
    queue    = [[start]]
    while queue:
        path = queue.pop(0)
        node = path[-1]
        for neighbour in GRAPH.get(node, {}).get("edges", {}).keys():
            if neighbour not in visited:
                new_path = path + [neighbour]
                if neighbour == end:
                    return new_path
                visited.add(neighbour)
                queue.append(new_path)
    return None


def _resolve(name: str) -> "str | None":
    """Resolve a user-supplied name to a canonical node ID."""
    key = name.strip().lower()
    # Direct node ID match
    if key in GRAPH:
        return key
    # Alias match
    if key in ALIASES:
        return ALIASES[key]
    # Partial alias match
    for alias, node_id in ALIASES.items():
        if key in alias or alias in key:
            return node_id
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE BUILDER
# Converts a list of node IDs into human-readable step-by-step directions.
# ═══════════════════════════════════════════════════════════════════════════════

def _build_directions(path: "list[str]") -> dict:
    """
    Given an ordered path of node IDs, returns a structured directions dict:
    {
        "steps": [
            {
                "step": 1,
                "location": "Quadrangle",
                "instruction": "Walk straight...",
                "image": "Quadrangle_or_Quad.jpg",
                "floor": "ground"
            },
            ...
        ],
        "total_steps": N,
        "via_quad": bool,
        "floors_involved": [...]
    }
    """
    steps   = []
    via_quad = False

    for i, node_id in enumerate(path):
        node  = GRAPH[node_id]
        label = node["label"]
        floor = node["floor"]
        image = node.get("image")

        if node_id == "campus_quad":
            via_quad = True

        # Instruction is the edge description FROM the previous node TO this one
        if i == 0:
            instruction = f"Start at {label}."
        else:
            prev_node = GRAPH[path[i - 1]]
            instruction = prev_node["edges"].get(node_id, f"Proceed to {label}.")

        steps.append({
            "step":        i + 1,
            "node_id":     node_id,
            "location":    label,
            "instruction": instruction,
            "image":       image,
            "floor":       floor,
        })

    floors_involved = sorted(
        set(s["floor"] for s in steps if isinstance(s["floor"], int))
    )

    return {
        "steps":           steps,
        "total_steps":     len(steps),
        "via_quad":        via_quad,
        "floors_involved": floors_involved,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NATURAL LANGUAGE SUMMARY
# Converts structured directions into a readable paragraph for the chatbot.
# ═══════════════════════════════════════════════════════════════════════════════

def _summarise(directions: dict, origin_label: str, dest_label: str) -> str:
    steps = directions["steps"]
    total = directions["total_steps"]
    via_q = directions["via_quad"]
    floors = directions["floors_involved"]

    lines = [
        f"**Directions from {origin_label} to {dest_label}** ({total} steps)\n"
    ]

    if via_q and steps[0]["node_id"] != "campus_quad":
        lines.append(
            "⚠️ You need to reach the **Quadrangle (Basketball Ground)** first — "
            "both staircases are visible from there.\n"
        )

    if floors:
        floor_str = " → ".join(f"Floor {f}" for f in floors)
        lines.append(f"🏢 Floors: {floor_str}\n")

    for s in steps:
        floor_tag = f"[Floor {s['floor']}] " if isinstance(s["floor"], int) else ""
        lines.append(f"**Step {s['step']}:** {floor_tag}{s['instruction']}")
        if s["image"]:
            lines.append(f"  📸 *Reference image: {s['image']}*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTION — called by backend_api.py navigation keyword intercept
# ═══════════════════════════════════════════════════════════════════════════════

def get_navigation(origin: str, destination: str) -> dict:
    """
    Main entry point.
    Returns:
        {
            "found": bool,
            "summary": str,          # human-readable directions
            "directions": dict,      # structured step-by-step data
            "error": str | None
        }
    """
    origin_id = _resolve(origin)
    dest_id   = _resolve(destination)

    if not origin_id:
        return {
            "found":      False,
            "summary":    f"Sorry, I don't recognise '{origin}' as a location. Try using names like 'quad', 'dsp lab', 'library', 'floor 2' etc.",
            "directions": None,
            "error":      f"Unknown origin: {origin}",
        }

    if not dest_id:
        return {
            "found":      False,
            "summary":    f"Sorry, I don't recognise '{destination}' as a location. Try using names like 'quad', 'dsp lab', 'library', 'floor 2' etc.",
            "directions": None,
            "error":      f"Unknown destination: {destination}",
        }

    if origin_id == dest_id:
        node = GRAPH[origin_id]
        return {
            "found":      True,
            "summary":    f"You are already at **{node['label']}**!",
            "directions": {"steps": [], "total_steps": 0, "via_quad": False, "floors_involved": []},
            "error":      None,
        }

    path = _bfs(origin_id, dest_id)

    if not path:
        return {
            "found":      False,
            "summary":    f"Sorry, I couldn't find a route from '{origin}' to '{destination}'. The navigation map may not be fully connected yet.",
            "directions": None,
            "error":      "No path found",
        }

    directions = _build_directions(path)
    summary    = _summarise(
        directions,
        GRAPH[origin_id]["label"],
        GRAPH[dest_id]["label"],
    )

    return {
        "found":      True,
        "summary":    summary,
        "directions": directions,
        "error":      None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@navigation_bp.route("/api/navigate", methods=["POST"])
def navigate_endpoint():
    """
    POST /api/navigate
    Body: { "from": "quad", "to": "dsp lab" }
    Returns full navigation result.
    """
    data        = request.json or {}
    origin      = data.get("from", "").strip()
    destination = data.get("to", "").strip()

    if not origin or not destination:
        return jsonify({"error": "Both 'from' and 'to' fields are required."}), 400

    result = get_navigation(origin, destination)
    return jsonify(result)


@navigation_bp.route("/api/navigate/locations", methods=["GET"])
def locations_endpoint():
    """
    GET /api/navigate/locations
    Returns all known locations with their labels, floors and aliases.
    Useful for the frontend to build autocomplete.
    """
    locations = []
    for node_id, node in GRAPH.items():
        aliases = [k for k, v in ALIASES.items() if v == node_id]
        locations.append({
            "id":      node_id,
            "label":   node["label"],
            "floor":   node["floor"],
            "image":   node.get("image"),
            "aliases": aliases,
        })

    locations.sort(key=lambda x: (str(x["floor"]), x["label"]))
    return jsonify({"locations": locations, "total": len(locations)})


@navigation_bp.route("/api/navigate/graph", methods=["GET"])
def graph_endpoint():
    """
    GET /api/navigate/graph
    Returns the full graph for debugging or frontend map rendering.
    """
    return jsonify({"graph": GRAPH, "aliases": ALIASES})


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION KEYWORD DETECTION
# Used by backend_api.py to intercept navigation questions before the LLM.
# ═══════════════════════════════════════════════════════════════════════════════

NAV_TRIGGER_PHRASES = {
    "how do i get to", "how to get to", "how to reach", "how do i reach",
    "navigate to", "navigate from", "directions to", "directions from",
    "way to", "path to", "route to", "route from",
    "take me to", "find my way to", "where is", "how to go to",
    "go from", "go to", "i want to go to", "i need to go to",
    "from quad to", "from quadrangle to", "from entrance to",
}


def detect_navigation_intent(user_message: str) -> "tuple[str, str] | None":
    """
    Checks if the user message is a navigation request.
    Returns (origin, destination) tuple if detected, else None.

    Examples it handles:
        "How do I get to the DSP lab?"           → ("campus_quad", "dsp lab")
        "Navigate from quad to library"           → ("quad", "library")
        "How to reach the Python lab from floor 1"→ ("floor 1", "python lab")
        "Where is the Women Development Cell?"    → ("campus_quad", "women development cell")
        "Directions from entrance to DSP lab"     → ("entrance", "dsp lab")
    """
    import re
    msg = user_message.lower().strip()

    # Explicit "from X to Y" — try progressively to match known locations
    explicit = re.search(
        r"from\s+(?:the\s+)?(.+?)\s+to\s+(?:the\s+)?(.+?)(?:\?|$|\.|,)", msg
    )
    if explicit:
        origin = explicit.group(1).strip()
        dest   = explicit.group(2).strip()
        # Clean trailing noise like "from floor 1" where "1" got appended to dest
        for suffix in [" from floor 1", " from floor 2", " from floor 3", " from quad", " from entrance"]:
            dest = dest.replace(suffix, "").strip()
        if _resolve(origin) and _resolve(dest):
            return (origin, dest)
        # Try swapping if origin not known (e.g. "reach python lab from floor 1")
        if not _resolve(origin) and _resolve(dest):
            # extract origin from trailing "from X"
            trailing = re.search(r"from\s+(.+?)(?:\?|$|\.)", msg.split(" to ")[1] if " to " in msg else "")
            if trailing:
                alt_origin = trailing.group(1).strip()
                if _resolve(alt_origin):
                    return (alt_origin, dest)

    # "how do I get to / where is / navigate to" — assume starting from quad
    destination_only = re.search(
        r"(?:how (?:do i |to )?(?:get to|reach|go to)|where is|navigate to|"
        r"directions to|take me to|way to|path to|route to|find my way to|"
        r"i (?:want|need) to go to)\s+(?:the\s+)?(.+?)(?:\?|$|\.|,)", msg
    )
    if destination_only:
        dest = destination_only.group(1).strip()
        if _resolve(dest):
            return ("campus_quad", dest)

    # Check if any nav trigger phrase is present + a known location is in message
    has_trigger = any(phrase in msg for phrase in NAV_TRIGGER_PHRASES)
    if has_trigger:
        # Try to find a destination — any known alias in the message
        for alias in sorted(ALIASES.keys(), key=len, reverse=True):
            if alias in msg:
                return ("campus_quad", alias)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# python navigation.py
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_cases = [
        ("campus_quad", "dsp lab"),
        ("campus_entrance", "python lab"),
        ("quad", "library"),
        ("entrance", "analog lab"),
        ("floor 1", "women development cell"),
        ("dsp lab", "dsp lab"),
        ("quad", "unknown place"),
    ]

    print("=" * 60)
    print("VJTI Navigation System — Self Test")
    print("=" * 60)

    for origin, dest in test_cases:
        print(f"\n🧭 {origin}  →  {dest}")
        result = get_navigation(origin, dest)
        if result["found"]:
            steps = result["directions"]["total_steps"]
            print(f"   ✅ Route found ({steps} steps)")
            for s in result["directions"]["steps"]:
                print(f"      Step {s['step']}: {s['instruction'][:70]}")
        else:
            print(f"   ❌ {result['summary']}")

    print("\n" + "=" * 60)
    print("Intent detection test:")
    msgs = [
        "How do I get to the DSP lab?",
        "Navigate from quad to library",
        "Where is the Women Development Cell?",
        "How to reach the Python lab from floor 1",
        "What is the cutoff for computer engineering?",  # should NOT trigger
    ]
    for m in msgs:
        result = detect_navigation_intent(m)
        print(f"  '{m[:50]}' → {result}")