"""Reference skill plans and goal-accurate instructions for the Robo Use BEHAVIOR suite.

One entry per 2026 BEHAVIOR Challenge activity that the skill set can solve. `plan` is the oracle: a list of
`robo skill` calls. `instruction` states what BEHAVIOR's BDDL goal checks. Where the challenge's own instruction
(challenge_tasks.json, `official`) says more or less than the goal, the instruction follows the goal.
"""

from __future__ import annotations


def nav(o):
    return [["navigate_to", o]]


def move(obj, rel, target, go=True):
    """navigate to obj, grasp it, navigate to target, place it (rel: inside | on)."""
    return (
        nav(obj)
        + [["grasp", obj]]
        + (nav(target) if go else [])
        + [["place_inside" if rel == "inside" else "place_on_top", target]]
    )


def into(target, *objs):
    return [s for o in objs for s in move(o, "inside", target)]


def onto(target, *objs):
    return [s for o in objs for s in move(o, "on", target)]


def opn(o):
    return nav(o) + [["open", o]]


def cls(o):
    return nav(o) + [["close", o]]


def n(cat, k):
    return [f"{cat}_{i}" for i in range(1, k + 1)]


FRIDGE = "electric_refrigerator.n.01_1"

TASKS = {
    "turning_on_radio": dict(
        instruction="Turn on the radio receiver that's on the table in the living room.",
        plan=nav("radio_receiver.n.01_1") + [["toggle_on", "radio_receiver.n.01_1"]],
    ),
    "picking_up_trash": dict(
        instruction="Put the three cans of soda from the living room inside the trash can in the kitchen.",
        plan=into("ashcan.n.01_1", *n("can__of__soda.n.01", 3)),
    ),
    "cleaning_up_plates_and_food": dict(
        instruction="From the breakfast table in the kitchen, move both pizzas, each still on its own plate, into the "
        "same refrigerator, put both bowls into one sink, and make sure every refrigerator is closed at the end.",
        plan=opn(FRIDGE)
        + into(FRIDGE, "plate.n.04_1", "plate.n.04_2")
        + into("sink.n.01_1", *n("bowl.n.01", 2))
        + cls(FRIDGE),
    ),
    "can_meat": dict(
        instruction="Take the two hinged jars out of the kitchen cabinet, put exactly two of the cooked bratwursts from "
        "the chopping board into each jar, close both jars, put both jars back inside that cabinet, and close "
        "the cabinet.",
        plan=opn("cabinet.n.01_1")
        + [
            s
            for j in ("hinged_jar.n.01_1", "hinged_jar.n.01_2")
            for s in [
                ["grasp", j],
                ["navigate_to", "chopping_board.n.01_1"],
                ["place_on_top", "countertop.n.01_1"],
                ["open", j],
                ["navigate_to", "cabinet.n.01_1"],
            ]
        ][:-1]
        + [
            s
            for j, b in (
                ("hinged_jar.n.01_1", 1),
                ("hinged_jar.n.01_1", 2),
                ("hinged_jar.n.01_2", 3),
                ("hinged_jar.n.01_2", 4),
            )
            for s in [["grasp", f"bratwurst.n.01_{b}"], ["place_inside", j]]
        ]
        + [["close", "hinged_jar.n.01_1"], ["close", "hinged_jar.n.01_2"]]
        + [
            s
            for j in ("hinged_jar.n.01_1", "hinged_jar.n.01_2")
            for s in [
                ["navigate_to", j],
                ["grasp", j],
                ["navigate_to", "cabinet.n.01_1"],
                ["place_inside", "cabinet.n.01_1"],
            ]
        ]
        + [["close", "cabinet.n.01_1"]],
    ),
    "picking_up_toys": dict(
        instruction="Put all the toys in the child's room (the three board games, two on the bed and one on the table, "
        "the two jigsaw puzzles and the tennis ball on the table) inside the toy box on the table in the "
        "child's room.",
        plan=into("toy_box.n.01_1", *n("board_game.n.01", 3), *n("jigsaw_puzzle.n.01", 2), "tennis_ball.n.01_1"),
    ),
    "rearranging_kitchen_furniture": dict(
        instruction="Move the toaster, food processor, and French press from the kitchen countertop into the same kitchen "
        "cabinet, and make sure that cabinet is closed at the end.",
        plan=opn("cabinet.n.01_1")
        + into("cabinet.n.01_1", "toaster.n.02_1", "food_processor.n.01_1", "french_press.n.01_1")
        + [["close", "cabinet.n.01_1"]],
    ),
    "putting_dishes_away_after_cleaning": dict(
        instruction="In the kitchen, gather all eight plates from the two countertops, place them all inside a single "
        "cabinet (either one), and make sure all cabinets are closed when you are done.",
        plan=opn("cabinet.n.01_2") + into("cabinet.n.01_2", *n("plate.n.04", 8)) + [["close", "cabinet.n.01_2"]],
    ),
    "preparing_lunch_box": dict(
        instruction="Put both apple halves, the club sandwich and the chocolate chip cookie from the chopping board on the "
        "kitchen countertop into the packing box on the countertop. Then take the bottle of tea out of the "
        "refrigerator, put it into the same box, and make sure the refrigerator is closed at the end.",
        plan=opn(FRIDGE)
        + into("packing_box.n.02_1", "bottle__of__tea.n.01_1")
        + cls(FRIDGE)
        + into("packing_box.n.02_1", "club_sandwich.n.01_1", *n("half__apple.n.01", 2), "chocolate_chip_cookie.n.01_1"),
    ),
    "loading_the_car": dict(
        instruction="Put the digital camera from the living room table into the container on the living room floor. Then "
        "put the container (with the camera in it) and the tennis racket inside the car in the garage, and "
        "make sure the car is closed at the end.",
        plan=into("container.n.01_1", "digital_camera.n.01_1")
        + opn("car.n.01_1")
        + into("car.n.01_1", "container.n.01_1", "tennis_racket.n.01_1")
        + [["close", "car.n.01_1"]],
    ),
    "carrying_in_groceries": dict(
        instruction="The sack of groceries is in the open car in the garage. Put the tomato and the carton of milk from it "
        "into the same refrigerator in the kitchen. At the end the car and the kitchen refrigerator "
        "electric_refrigerator.n.01_1 must both be closed.",
        plan=opn(FRIDGE)
        + into(FRIDGE, "beefsteak_tomato.n.01_1", "carton__of__milk.n.01_1")
        + cls(FRIDGE)
        + cls("car.n.01_1"),
    ),
    "bringing_in_wood": dict(
        instruction="Bring the three plywood sheets from the garden into the corridor and put them on the corridor floor "
        "(floor.n.01_2).",
        plan=onto("floor.n.01_2", *n("plywood.n.01", 3)),
    ),
    "moving_boxes_to_storage": dict(
        instruction="Move the two storage containers from the living room to the garage: one on the garage floor "
        "(floor.n.01_2) and the other stacked on top of it (either order).",
        plan=onto("floor.n.01_2", "storage_container.n.01_1")
        + onto("storage_container.n.01_1", "storage_container.n.01_2"),
    ),
    "bringing_water": dict(
        instruction="Retrieve the two bottles from the refrigerator in the kitchen, bring them to the living room, and "
        "place both on the coffee table. Make sure the refrigerator is closed when you finish.",
        plan=opn(FRIDGE) + onto("coffee_table.n.01_1", *n("bottle.n.01", 2)) + cls(FRIDGE),
    ),
    "outfit_a_basic_toolbox": dict(
        instruction="In the utility room, put the drill, pliers, flashlight, Allen wrench and screwdriver from the tabletop "
        "into the toolbox, keep the toolbox on the tabletop, and make sure the toolbox is closed at the end.",
        plan=opn("toolbox.n.01_1")
        + into(
            "toolbox.n.01_1",
            "drill.n.01_1",
            "pliers.n.01_1",
            "flashlight.n.01_1",
            "allen_wrench.n.01_1",
            "screwdriver.n.01_1",
        )
        + [["close", "toolbox.n.01_1"]],
    ),
    "sorting_vegetables": dict(
        instruction="Sort the vegetables from the two wicker baskets on the kitchen floor into the three mixing bowls on "
        "the kitchen countertop: all three bok choy and all three Vidalia onions together in one bowl, both "
        "leeks and both broccoli together in a second bowl, and all three sweet corn in a third bowl.",
        plan=into("mixing_bowl.n.01_1", *n("bok_choy.n.02", 3), *n("vidalia_onion.n.01", 3))
        + into("mixing_bowl.n.01_2", *n("leek.n.02", 2), *n("broccoli.n.02", 2))
        + into("mixing_bowl.n.01_3", *n("sweet_corn.n.02", 3)),
    ),
    "collecting_childrens_toys": dict(
        instruction="Put the two dice from the bed, the two teddy bears from the floor, the two board games (one on the "
        "desk, one on the bed) and the train set on the desk all inside the same bookcase in the child's room.",
        plan=into(
            "bookcase.n.01_1", *n("die.n.01", 2), *n("teddy.n.01", 2), *n("board_game.n.01", 2), "train_set.n.01_1"
        ),
    ),
    "boxing_books_up_for_storage": dict(
        instruction="Put all six books from the bookcases in the living room into the box on the living room floor.",
        plan=into("box.n.01_1", *n("book.n.02", 6)),
    ),
    "storing_food": dict(
        instruction="Put away the food on the kitchen countertop: every box of oatmeal, bag of chips, bottle of olive oil "
        "and jar of sugar (two of each) must end up inside a kitchen cabinet (any cabinet, items may be split).",
        plan=opn("cabinet.n.01_1")
        + into(
            "cabinet.n.01_1",
            *n("box__of__oatmeal.n.01", 2),
            *n("bag__of__chips.n.01", 2),
            *n("bottle__of__olive_oil.n.01", 2),
            *n("jar__of__sugar.n.01", 2),
        ),
    ),
    "clearing_food_from_table_into_fridge": dict(
        instruction="Pack the half chicken and the half apple pie from the plates on the breakfast table into the two "
        "tupperware containers on the countertop (any assignment), then put both tupperware containers inside "
        "the refrigerator in the kitchen and make sure the refrigerator is closed at the end.",
        plan=into("tupperware.n.01_1", "half__chicken.n.01_1")
        + into("tupperware.n.01_2", "half__apple_pie.n.01_1")
        + opn(FRIDGE)
        + into(FRIDGE, "tupperware.n.01_1", "tupperware.n.01_2")
        + cls(FRIDGE),
    ),
    "assembling_gift_baskets": dict(
        instruction="Put one candle, one butter cookie, one piece of Swiss cheese and one bow from the table into each of "
        "the four wicker baskets on the living room floor (each basket gets exactly one of each).",
        plan=[
            s
            for i in range(1, 5)
            for s in into(
                f"wicker_basket.n.01_{i}",
                f"candle.n.01_{i}",
                f"butter_cookie.n.01_{i}",
                f"swiss_cheese.n.01_{i}",
                f"bow.n.08_{i}",
            )
        ],
    ),
    "clean_up_your_desk": dict(
        instruction="In the child's room: put both folders and both paperback books into the bookcase; put the pencil and "
        "both pens into the pencil box and leave the pencil box on the desk; take the stapler out of the "
        "bookcase and put it on the desk; move the laptop from the bed onto the desk and close it.",
        plan=onto("desk.n.01_1", "stapler.n.01_1")
        + into("bookcase.n.01_1", *n("folder.n.02", 2), *n("paperback_book.n.01", 2))
        + into("pencil_box.n.01_1", "pencil.n.01_1", *n("pen.n.01", 2))
        + onto("desk.n.01_1", "laptop.n.01_1")
        + [["close", "laptop.n.01_1"]],
    ),
    "freeze_fruit": dict(
        instruction="In the kitchen, take the two tupperware containers out of the cabinet, put one apple and one "
        "strawberry into each container, then put both containers inside the refrigerator and make sure the "
        "refrigerator is closed at the end.",
        plan=opn("cabinet.n.01_1")
        + onto("countertop.n.01_1", *n("tupperware.n.01", 2))
        + into("tupperware.n.01_1", "apple.n.01_1", "strawberry.n.01_1")
        + into("tupperware.n.01_2", "apple.n.01_2", "strawberry.n.01_2")
        + opn(FRIDGE)
        + into(FRIDGE, *n("tupperware.n.01", 2))
        + cls(FRIDGE),
    ),
    "sorting_bottles_cans_and_paper": dict(
        instruction="Sort the recyclables into the three buckets on the kitchen floor: both wine bottles together in one "
        "bucket, both soda cans together in a second bucket, and the newspaper and the magazine together in "
        "a third bucket, with nothing else in each of those buckets.",
        plan=into("bucket.n.01_3", "newspaper.n.03_1", "magazine.n.02_1")
        + into("bucket.n.01_1", *n("wine_bottle.n.01", 2))
        + into("bucket.n.01_2", *n("can__of__soda.n.01", 2)),
    ),
    "tidying_living_room": dict(
        instruction="In the living room: put the potted plant and the newspaper on the coffee table, the hardback book "
        "inside a bookcase, and the notebook on the desk.",
        plan=onto("coffee_table.n.01_1", "newspaper.n.03_1")
        + into("bookcase.n.01_1", "hardback.n.01_1")
        + onto("desk.n.01_1", "notebook.n.01_1")
        + onto("coffee_table.n.01_1", "pot_plant.n.01_1"),
    ),
    "putting_away_toys": dict(
        instruction="Pick up all eight toy figures from the floors of the living room and the dining room and put each of "
        "them inside one of the two toy boxes (either box).",
        plan=into("toy_box.n.01_1", *n("toy_figure.n.01", 4))
        + into("toy_box.n.01_2", *[f"toy_figure.n.01_{i}" for i in range(5, 9)]),
    ),
    "re_shelving_library_books": dict(
        instruction="Put the three books from the table in the living room inside the bookcases (any bookcase).",
        plan=into("bookcase.n.01_1", *n("book.n.02", 3)),
    ),
    "make_rose_centerpieces": dict(
        instruction="Put the vase on the coffee table in the living room and put all three roses inside the vase.",
        plan=onto("coffee_table.n.01_1", "vase.n.01_1") + into("vase.n.01_1", *n("rose.n.01", 3)),
    ),
    "organizing_art_supplies": dict(
        instruction="Put the marker, paintbrush, glue stick and rubber eraser into the tote bag (carryall), and leave the "
        "tote bag on the desk in the bedroom.",
        plan=onto("desk.n.01_1", "carryall.n.01_1")
        + into("carryall.n.01_1", "marker.n.03_1", "paintbrush.n.01_1", "glue_stick.n.01_1", "rubber_eraser.n.01_1"),
    ),
    "bringing_paper_to_recycling": dict(
        instruction="Put the paper sack from the kitchen floor and the newspaper from the kitchen countertop into the "
        "recycling bin in the garden, and make sure the recycling bin is closed at the end.",
        plan=opn("recycling_bin.n.01_1")
        + into("recycling_bin.n.01_1", "sack.n.01_1", "newspaper.n.03_1")
        + [["close", "recycling_bin.n.01_1"]],
    ),
    "turning_out_all_lights_before_sleep": dict(
        instruction="Turn off all three light switches and both table lamps.",
        plan=[s for o in n("switch.n.01", 3) + n("table_lamp.n.01", 2) for s in nav(o) + [["toggle_off", o]]],
    ),
    "boxing_food_after_dinner": dict(
        instruction="Take the tupperware container out of the kitchen cabinet, put both tacos from the plates into it, put "
        "both plates on the kitchen sink, then put the tupperware container inside the refrigerator and make "
        "sure the refrigerator is closed at the end.",
        plan=opn("cabinet.n.01_1")
        + onto("countertop.n.01_1", "tupperware.n.01_1")
        + into("tupperware.n.01_1", *n("taco.n.02", 2))
        + onto("sink.n.01_1", *n("plate.n.04", 2))
        + opn(FRIDGE)
        + into(FRIDGE, "tupperware.n.01_1")
        + cls(FRIDGE),
    ),
    "cleaning_up_branches_and_twigs": dict(
        instruction="Put all four branches in the garden into the recycling bin, and leave the recycling bin standing on "
        "the garden floor.",
        plan=opn("recycling_bin.n.01_1") + into("recycling_bin.n.01_1", *n("branch.n.02", 4)),
    ),
    "organizing_school_stuff": dict(
        instruction="Put the folder, book, pencil, pen and calculator into the tote bag (carryall), and leave the tote bag "
        "on the bed in the bedroom.",
        plan=onto("bed.n.01_1", "carryall.n.01_1")
        + into("carryall.n.01_1", "folder.n.02_1", "book.n.02_1", "pencil.n.01_1", "pen.n.01_1", "calculator.n.02_1"),
    ),
    "carrying_out_garden_furniture": dict(
        instruction="Carry the lawn chair from the living room to the garden and put it on the garden floor "
        "(floor.n.01_2), and put the wheelbarrow on the lawn.",
        plan=onto("floor.n.01_2", "lawn_chair.n.01_1") + onto("lawn.n.01_1", "barrow.n.03_1"),
    ),
    "put_together_a_basic_pruning_kit": dict(
        instruction="Put the pruner and the shears into the toolbox on the garage floor, leave the toolbox on the floor, "
        "and make sure the toolbox is closed at the end.",
        plan=opn("toolbox.n.01_1")
        + into("toolbox.n.01_1", "pruner.n.02_1", "shears.n.01_1")
        + [["close", "toolbox.n.01_1"]],
    ),
    "dispose_of_glass": dict(
        instruction="Put the four water glasses from the bathroom sink into the trash can.",
        plan=into("ashcan.n.01_1", *n("water_glass.n.02", 4)),
    ),
    "clean_up_broken_glass": dict(
        instruction="Put all three pieces of broken glass from the dining room floor into the trash can.",
        plan=into("ashcan.n.01_1", *n("broken__glass.n.01", 3)),
    ),
    "packing_meal_for_delivery": dict(
        instruction="Put each of the three wrapped hamburgers into its own paper sack (one hamburger per sack), and put all "
        "three sacks on top of the storage container.",
        plan=[s for i in (1, 2, 3) for s in into(f"sack.n.01_{i}", f"wrapped_hamburger.n.01_{i}")]
        + onto("storage_container.n.01_1", *n("sack.n.01", 3)),
    ),
    "store_batteries": dict(
        instruction="Put all three batteries inside the same cabinet in the living room (either cabinet).",
        plan=opn("cabinet.n.01_1") + into("cabinet.n.01_1", *n("battery.n.02", 3)),
    ),
    "store_honey": dict(
        instruction="Put the jar of honey from the kitchen countertop inside the cabinet in the entryway.",
        plan=opn("cabinet.n.01_1") + into("cabinet.n.01_1", "jar__of__honey.n.01_1"),
    ),
    "tidying_bathroom": dict(
        instruction="In the bathroom: put the bar of soap on the soap dish, the tissue dispenser on the sink, the roll of "
        "toilet tissue on the toilet, and the cork inside the trash can.",
        plan=onto("soap_dish.n.01_1", "bar_soap.n.01_1")
        + onto("sink.n.01_1", "tissue_dispenser.n.01_1")
        + onto("toilet.n.02_1", "toilet_tissue.n.01_1")
        + into("ashcan.n.01_1", "cork.n.04_1"),
    ),
    "putting_dirty_dishes_in_sink": dict(
        instruction="Put both bowls and both plates from the booth in the dining room inside the kitchen sink.",
        plan=into("sink.n.01_1", *n("bowl.n.01", 2), *n("plate.n.04", 2)),
    ),
    "make_gift_bags_for_baby_showers": dict(
        instruction="Put both paper sacks on the coffee table in the living room, then put one toy die and one wafer into "
        "each sack (each sack gets exactly one of each). The wafers are in the cabinet.",
        plan=onto("coffee_table.n.01_1", *n("sack.n.01", 2))
        + opn("cabinet.n.01_1")
        + into("sack.n.01_1", "toy_dice.n.01_1", "wafer.n.02_1")
        + into("sack.n.01_2", "toy_dice.n.01_2", "wafer.n.02_2"),
    ),
    "collecting_aluminum_cans": dict(
        instruction="Put all six soda cans (three on the bed, three on the floor) into the bucket in the bedroom.",
        plan=into("bucket.n.01_1", *n("can__of__soda.n.01", 6)),
    ),
    "rearrange_your_room": dict(
        instruction="Put the tissue dispenser on a nightstand, and put the two pillows from the floor on the two beds, one "
        "pillow per bed.",
        plan=onto("stand.n.04_1", "tissue_dispenser.n.01_1")
        + onto("bed.n.01_1", "pillow.n.01_1")
        + onto("bed.n.01_2", "pillow.n.01_2"),
    ),
    "installing_a_fax_machine": dict(
        instruction="Put the fax machine from the floor on one of the cubicle desks (carrels) in the shared office and "
        "turn it on.",
        plan=onto("carrel.n.02_1", "facsimile.n.02_1") + [["toggle_on", "facsimile.n.02_1"]],
    ),
    "composting_waste": dict(
        instruction="Put the half banana and the half pomegranate from the kitchen countertop into the trash can in the "
        "kitchen.",
        plan=into("ashcan.n.01_1", "half__banana.n.01_1", "half__pomegranate.n.01_1"),
    ),
    "store_produce": dict(
        instruction="Take both mangoes and both pomegranates out of the wicker basket and put all four inside the same "
        "refrigerator in the kitchen.",
        plan=opn(FRIDGE) + into(FRIDGE, *n("mango.n.02", 2), *n("pomegranate.n.02", 2)),
    ),
    "dispose_of_batteries": dict(
        instruction="Put all three batteries (two on the desk in the private office, one on the cabinet in the copy room) "
        "into the trash can in the copy room, and leave the trash can on the floor.",
        plan=into("ashcan.n.01_1", *n("battery.n.02", 3)),
    ),
    "sorting_books_on_shelf": dict(
        instruction="Keep every comic book, notebook and hardback inside the bookcase, and stack them by type: at least "
        "two comic books each on top of another comic book, one notebook on top of the other notebook, and one "
        "hardback on top of the other hardback.",
        plan=[
            ["navigate_to", "bookcase.n.01_1"],
            ["grasp", "hardback.n.01_2"],
            ["place_on_top", "hardback.n.01_1"],
            ["grasp", "comic_book.n.01_2"],
            ["place_on_top", "comic_book.n.01_3"],
            ["grasp", "notebook.n.01_2"],
            ["place_on_top", "notebook.n.01_1"],
            ["grasp", "comic_book.n.01_1"],
            ["place_on_top", "comic_book.n.01_2"],
        ],
    ),
}
