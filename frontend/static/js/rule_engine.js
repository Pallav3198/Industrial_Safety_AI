// static/js/rule_engine.js
// Recursive AND/OR condition-tree builder for the Rule Engine's
// Add/Edit Rule page. Keeps the whole tree in one JS object and
// re-renders it into #ruleTreeContainer on every change; on submit,
// serializes it into the hidden #conditionTreeInput field as JSON for
// the server to parse.

function initRuleBuilder(catalog, initialTree) {
    let tree = initialTree || { type: "group", id: cryptoId(), logic: "ALL", children: [] };

    function cryptoId() {
        return Math.random().toString(16).slice(2, 10);
    }

    function newCondition() {
        const firstSection = Object.keys(catalog)[0];
        const firstType = catalog[firstSection].condition_types[0];
        return {
            type: "condition",
            id: cryptoId(),
            section: firstSection,
            condition_type: firstType.key,
            scope: "any",
            target_id: "",
            operator: "",
            value: "",
            notes: "",
        };
    }

    function newGroup() {
        return { type: "group", id: cryptoId(), logic: "ALL", children: [] };
    }

    function findAndMutate(node, targetId, fn) {
        if (!node.children) return false;
        for (let i = 0; i < node.children.length; i++) {
            if (node.children[i].id === targetId) {
                fn(node.children, i);
                return true;
            }
            if (node.children[i].type === "group" && findAndMutate(node.children[i], targetId, fn)) {
                return true;
            }
        }
        return false;
    }

    function render() {
        const container = document.getElementById("ruleTreeContainer");
        container.innerHTML = "";
        container.appendChild(renderGroup(tree, true));
        document.getElementById("conditionTreeInput").value = JSON.stringify(tree);
    }

    function renderGroup(group, isRoot) {
        const box = document.createElement("div");
        box.className = "rule-group-box" + (isRoot ? " rule-group-root" : "");

        const header = document.createElement("div");
        header.className = "rule-group-header";

        const logicSelect = document.createElement("select");
        logicSelect.className = "form-select form-select-sm d-inline-block w-auto";
        ["ALL", "ANY"].forEach(function (opt) {
            const o = document.createElement("option");
            o.value = opt;
            o.textContent = opt === "ALL" ? "ALL of the following (AND)" : "ANY of the following (OR)";
            if (group.logic === opt) o.selected = true;
            logicSelect.appendChild(o);
        });
        logicSelect.addEventListener("change", function () {
            group.logic = logicSelect.value;
        });
        header.appendChild(logicSelect);

        const addCondBtn = document.createElement("button");
        addCondBtn.type = "button";
        addCondBtn.className = "btn btn-sm btn-outline-primary ms-2";
        addCondBtn.innerHTML = '<i class="bi bi-plus-lg"></i> Condition';
        addCondBtn.addEventListener("click", function () {
            group.children.push(newCondition());
            render();
        });
        header.appendChild(addCondBtn);

        const addGroupBtn = document.createElement("button");
        addGroupBtn.type = "button";
        addGroupBtn.className = "btn btn-sm btn-outline-secondary ms-2";
        addGroupBtn.innerHTML = '<i class="bi bi-plus-lg"></i> Nested Group';
        addGroupBtn.addEventListener("click", function () {
            group.children.push(newGroup());
            render();
        });
        header.appendChild(addGroupBtn);

        if (!isRoot) {
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "btn btn-sm btn-outline-danger ms-2";
            removeBtn.innerHTML = '<i class="bi bi-trash"></i> Remove Group';
            removeBtn.addEventListener("click", function () {
                findAndMutate(tree, group.id, function (arr, idx) { arr.splice(idx, 1); });
                render();
            });
            header.appendChild(removeBtn);
        }

        box.appendChild(header);

        const childrenWrap = document.createElement("div");
        childrenWrap.className = "rule-group-children";
        group.children.forEach(function (child) {
            if (child.type === "group") {
                childrenWrap.appendChild(renderGroup(child, false));
            } else {
                childrenWrap.appendChild(renderCondition(child));
            }
        });
        if (group.children.length === 0) {
            const empty = document.createElement("div");
            empty.className = "text-muted small fst-italic py-2";
            empty.textContent = "No conditions yet -- add one above.";
            childrenWrap.appendChild(empty);
        }
        box.appendChild(childrenWrap);

        return box;
    }

    function renderCondition(cond) {
        const row = document.createElement("div");
        row.className = "rule-condition-row";

        const sectionSelect = document.createElement("select");
        sectionSelect.className = "form-select form-select-sm";
        Object.keys(catalog).forEach(function (key) {
            const o = document.createElement("option");
            o.value = key;
            o.textContent = catalog[key].label;
            if (cond.section === key) o.selected = true;
            sectionSelect.appendChild(o);
        });
        sectionSelect.addEventListener("change", function () {
            cond.section = sectionSelect.value;
            cond.condition_type = catalog[cond.section].condition_types[0].key;
            render();
        });

        const typeSelect = document.createElement("select");
        typeSelect.className = "form-select form-select-sm";
        catalog[cond.section].condition_types.forEach(function (ct) {
            const o = document.createElement("option");
            o.value = ct.key;
            o.textContent = ct.label + (ct.live_data_pending ? " (awaiting live data)" : "");
            if (cond.condition_type === ct.key) o.selected = true;
            typeSelect.appendChild(o);
        });
        typeSelect.addEventListener("change", function () {
            cond.condition_type = typeSelect.value;
            render();
        });

        const scopeSelect = document.createElement("select");
        scopeSelect.className = "form-select form-select-sm";
        [["specific", "This specific record"], ["any", "Any record"], ["all", "All records"]].forEach(function (pair) {
            const o = document.createElement("option");
            o.value = pair[0];
            o.textContent = pair[1];
            if (cond.scope === pair[0]) o.selected = true;
            scopeSelect.appendChild(o);
        });
        scopeSelect.addEventListener("change", function () {
            cond.scope = scopeSelect.value;
            render();
        });

        const targetInput = document.createElement("input");
        targetInput.type = "text";
        targetInput.className = "form-control form-control-sm";
        targetInput.placeholder = "Record ID or name";
        targetInput.value = cond.target_id;
        targetInput.style.display = cond.scope === "specific" ? "" : "none";
        targetInput.addEventListener("input", function () {
            cond.target_id = targetInput.value;
            document.getElementById("conditionTreeInput").value = JSON.stringify(tree);
        });

        const currentType = catalog[cond.section].condition_types.find(function (ct) { return ct.key === cond.condition_type; });
        const takesValue = currentType ? currentType.takes_value : false;

        const operatorSelect = document.createElement("select");
        operatorSelect.className = "form-select form-select-sm";
        operatorSelect.style.display = takesValue ? "" : "none";
        [">", ">=", "<", "<=", "=="].forEach(function (op) {
            const o = document.createElement("option");
            o.value = op;
            o.textContent = op;
            if (cond.operator === op) o.selected = true;
            operatorSelect.appendChild(o);
        });
        operatorSelect.addEventListener("change", function () {
            cond.operator = operatorSelect.value;
            document.getElementById("conditionTreeInput").value = JSON.stringify(tree);
        });

        const valueInput = document.createElement("input");
        valueInput.type = "text";
        valueInput.className = "form-control form-control-sm";
        valueInput.placeholder = "Value";
        valueInput.value = cond.value;
        valueInput.style.display = takesValue ? "" : "none";
        valueInput.addEventListener("input", function () {
            cond.value = valueInput.value;
            document.getElementById("conditionTreeInput").value = JSON.stringify(tree);
        });

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "btn btn-sm btn-outline-danger";
        removeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
        removeBtn.addEventListener("click", function () {
            findAndMutate(tree, cond.id, function (arr, idx) { arr.splice(idx, 1); });
            render();
        });

        [sectionSelect, typeSelect, scopeSelect, targetInput, operatorSelect, valueInput, removeBtn].forEach(function (el) {
            row.appendChild(el);
        });

        if (currentType && currentType.live_data_pending) {
            const badge = document.createElement("span");
            badge.className = "badge text-bg-warning ms-1";
            badge.textContent = "Awaiting live data";
            row.appendChild(badge);
        }

        return row;
    }

    render();

    document.getElementById("ruleBuilderForm").addEventListener("submit", function () {
        document.getElementById("conditionTreeInput").value = JSON.stringify(tree);
    });
}