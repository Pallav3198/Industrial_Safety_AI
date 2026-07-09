/**
 * layout_editor.js
 * -------------------
 * Interactive facility layout canvas (Step 4), built on Konva.js.
 *
 * Adapted from a standalone prototype with three changes:
 *   1. "Add Line" is now actually implemented -- the original prototype
 *      had a button with no click handler wired up at all.
 *   2. Shapes are persisted server-side (POST /factory/<id>/layout/save)
 *      instead of just alert()-ing the exported JSON, and previously
 *      saved shapes are reconstructed on page load from
 *      window.INITIAL_LAYOUT_DATA (see add_facility_step4_layout.html).
 *   3. The "Next" button auto-saves before navigating, so layout work
 *      is never silently lost by forgetting to click Save first.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const container = document.getElementById("layoutContainer");
    const saveStatus = document.getElementById("layoutSaveStatus");
    const nextBtn = document.getElementById("nextBtn");

    const CANVAS_HEIGHT = 550;

    const stage = new Konva.Stage({
        container: "layoutContainer",
        width: container.clientWidth,
        height: CANVAS_HEIGHT,
    });

    const layer = new Konva.Layer();
    stage.add(layer);

    // Keep the canvas width responsive without rescaling/distorting any
    // shapes already placed -- just changes the visible drawing area.
    window.addEventListener("resize", () => {
        stage.width(container.clientWidth);
    });

    // --- Grid ---------------------------------------------------------------
    // Grid lines are tagged with isGrid=true so exportLayoutData() can
    // reliably exclude them -- they're Konva.Line instances just like
    // user-placed lines, so instanceof alone can't tell them apart.
    function drawGrid() {
        for (let i = 0; i < stage.width(); i += 40) {
            layer.add(new Konva.Line({ points: [i, 0, i, stage.height()], stroke: "#E5E9EF", listening: false, isGrid: true }));
        }
        for (let i = 0; i < stage.height(); i += 40) {
            layer.add(new Konva.Line({ points: [0, i, stage.width(), i], stroke: "#E5E9EF", listening: false, isGrid: true }));
        }
    }
    drawGrid();

    // --- Selection / Transformer ---------------------------------------------
    const transformer = new Konva.Transformer();
    layer.add(transformer);
    let selected = null;

    function selectShape(shape) {
        selected = shape;
        transformer.nodes([shape]);
    }

    // Click on empty canvas space deselects whatever was selected.
    stage.on("click", (e) => {
        if (e.target === stage) {
            transformer.nodes([]);
            selected = null;
        }
    });

    // Successive new shapes are offset a bit so repeated clicks on the
    // same toolbar button don't stack shapes exactly on top of each other.
    let placementCounter = 0;
    function nextOffset() {
        placementCounter += 1;
        return (placementCounter % 8) * 25;
    }

    // --- Add Machine ------------------------------------------------------
    function addMachine(props) {
        props = props || {};
        const offset = nextOffset();
        const group = new Konva.Group({
            x: props.x ?? (100 + offset),
            y: props.y ?? (100 + offset),
            draggable: true,
        });

        const rect = new Konva.Rect({
            width: props.width ?? 140,
            height: props.height ?? 80,
            fill: "#8ecae6",
            stroke: "#1E3A5F",
            strokeWidth: 2,
            cornerRadius: 4,
        });

        const text = new Konva.Text({
            text: props.label ?? "Machine",
            width: props.width ?? 140,
            align: "center",
            y: 30,
            fontSize: 16,
            fontFamily: "Inter, Arial, sans-serif",
        });

        group.add(rect);
        group.add(text);

        group.on("click", () => selectShape(group));
        text.on("dblclick", () => {
            const value = prompt("Machine name", text.text());
            if (value) text.text(value);
            layer.draw();
        });

        layer.add(group);
        layer.draw();
        return group;
    }

    // --- Add Text -----------------------------------------------------------
    function addText(props) {
        props = props || {};
        const offset = nextOffset();
        const txt = new Konva.Text({
            x: props.x ?? (250 + offset),
            y: props.y ?? (250 + offset),
            text: props.text ?? "Double-click to edit",
            fontSize: 20,
            fontFamily: "Inter, Arial, sans-serif",
            fill: "#1F2937",
            draggable: true,
        });

        txt.on("click", () => selectShape(txt));
        txt.on("dblclick", () => {
            const value = prompt("Text", txt.text());
            if (value) txt.text(value);
            layer.draw();
        });

        layer.add(txt);
        layer.draw();
        return txt;
    }

    // --- Add Line (NEW -- the original prototype's button did nothing) -------
    function addLine(props) {
        props = props || {};
        const offset = nextOffset();
        const points = props.points ?? [100 + offset, 300 + offset, 300 + offset, 300 + offset];

        const line = new Konva.Line({
            points: points,
            stroke: "#1E3A5F",
            strokeWidth: 3,
            lineCap: "round",
            draggable: true,
            hitStrokeWidth: 12, // easier to click/select a thin line
        });

        line.on("click", () => selectShape(line));

        layer.add(line);
        layer.draw();
        return line;
    }

    // --- Delete ---------------------------------------------------------------
    window.addEventListener("keydown", (e) => {
        if (e.key === "Delete" && selected) {
            selected.destroy();
            transformer.nodes([]);
            selected = null;
            layer.draw();
        }
    });

    // --- Reconstruct previously saved layout, if any --------------------------
    (window.INITIAL_LAYOUT_DATA || []).forEach((shape) => {
        if (shape.type === "machine") {
            addMachine(shape);
        } else if (shape.type === "text") {
            addText(shape);
        } else if (shape.type === "line") {
            addLine(shape);
        }
    });

    // --- Export current canvas state to the same JSON shape used for save ----
    function exportLayoutData() {
        const objects = [];
        layer.children.forEach((obj) => {
            if (obj instanceof Konva.Transformer) return;      // skip the transformer itself
            if (obj.getAttr("isGrid")) return;                  // skip background grid lines

            if (obj instanceof Konva.Group) {
                const rect = obj.children[0];
                const text = obj.children[1];
                objects.push({
                    type: "machine",
                    x: obj.x(),
                    y: obj.y(),
                    width: rect.width() * obj.scaleX(),
                    height: rect.height() * obj.scaleY(),
                    label: text.text(),
                });
            } else if (obj instanceof Konva.Text) {
                objects.push({ type: "text", x: obj.x(), y: obj.y(), text: obj.text() });
            } else if (obj instanceof Konva.Line) {
                objects.push({ type: "line", points: obj.points(), x: obj.x(), y: obj.y() });
            }
        });
        return objects;
    }

    // --- Save to server ---------------------------------------------------------
    async function saveLayoutToServer() {
        const layoutData = exportLayoutData();
        saveStatus.textContent = "Saving…";
        try {
            const response = await fetch(`/factory/${factoryId}/layout/save`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ layout_data: layoutData }),
            });
            const result = await response.json();
            if (result.success) {
                saveStatus.textContent = `Saved (${result.shape_count} shape${result.shape_count === 1 ? "" : "s"})`;
            } else {
                saveStatus.textContent = "Save failed: " + (result.error || "unknown error");
            }
        } catch (err) {
            saveStatus.textContent = "Save failed: network error";
            console.error(err);
        }
        setTimeout(() => { saveStatus.textContent = ""; }, 4000);
    }

    // --- Wire up buttons ---------------------------------------------------------
    document.getElementById("machineBtn").onclick = () => addMachine();
    document.getElementById("textBtn").onclick = () => addText();
    document.getElementById("lineBtn").onclick = () => addLine();
    document.getElementById("saveBtn").onclick = saveLayoutToServer;

    // Auto-save before leaving via Next, so layout work is never lost by
    // forgetting to click Save first. Navigation proceeds either way --
    // a transient save failure shouldn't trap the user on this page.
    nextBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        await saveLayoutToServer();
        window.location.href = nextBtn.href;
    });
});