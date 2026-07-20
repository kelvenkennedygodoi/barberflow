(function () {
    const form = document.getElementById("agendamento-publico-form");
    if (!form) return;

    const steps = [...form.querySelectorAll("[data-step]")];
    const progress = [...document.querySelectorAll("[data-progress]")];
    const serviceInputs = [...form.querySelectorAll('input[name="servico"]')];
    const professionalInputs = [...form.querySelectorAll('input[name="profissional"]')];
    const dateInput = document.getElementById("id_data");
    const timeSelect = document.getElementById("id_horario");
    const timeOptions = document.getElementById("time-options");
    const timeHelp = document.getElementById("time-help");
    const status = document.getElementById("booking-status");
    const submit = document.getElementById("booking-submit");
    const phone = document.getElementById("id_telefone");
    let currentStep = form.querySelector(".field-error")?.closest("[data-step]")?.dataset.step || "1";

    function announce(message) {
        if (status) status.textContent = message;
    }

    function showStep(number) {
        currentStep = String(number);
        steps.forEach((step) => step.classList.toggle("active", step.dataset.step === currentStep));
        progress.forEach((item) => {
            const value = Number(item.dataset.progress);
            item.classList.toggle("active", value === Number(currentStep));
            item.classList.toggle("complete", value < Number(currentStep));
        });
        document.querySelector(".public-booking-card")?.scrollIntoView({behavior: "smooth", block: "start"});
        announce(`Etapa ${currentStep} de 4`);
        if (currentStep === "4") updateSummary();
    }

    function checked(inputs) {
        return inputs.find((input) => input.checked);
    }

    function validateStep() {
        if (currentStep === "1" && !checked(serviceInputs)) return "Escolha um serviço para continuar.";
        if (currentStep === "2" && !checked(professionalInputs)) return "Escolha um profissional para continuar.";
        if (currentStep === "3" && (!dateInput.value || !timeSelect.value)) return "Escolha uma data e um horário para continuar.";
        return "";
    }

    form.querySelectorAll(".js-next").forEach((button) => button.addEventListener("click", () => {
        const error = validateStep();
        if (error) { announce(error); alert(error); return; }
        showStep(Math.min(4, Number(currentStep) + 1));
    }));
    form.querySelectorAll(".js-back").forEach((button) => button.addEventListener("click", () => showStep(Math.max(1, Number(currentStep) - 1))));

    function renderTimes(items, previous) {
        timeOptions.innerHTML = "";
        items.forEach((item) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "time-option";
            button.textContent = item.texto;
            button.dataset.value = item.valor;
            button.setAttribute("aria-pressed", String(item.valor === previous));
            if (item.valor === previous) button.classList.add("selected");
            button.addEventListener("click", () => {
                timeSelect.value = item.valor;
                timeOptions.querySelectorAll(".time-option").forEach((option) => {
                    const selected = option === button;
                    option.classList.toggle("selected", selected);
                    option.setAttribute("aria-pressed", String(selected));
                });
                announce(`Horário ${item.texto} selecionado.`);
            });
            timeOptions.appendChild(button);
        });
    }

    async function loadTimes() {
        const service = checked(serviceInputs);
        const professional = checked(professionalInputs);
        const previous = timeSelect.value;
        if (!service || !professional || !dateInput.value) {
            timeOptions.innerHTML = "";
            timeHelp.textContent = "Selecione serviço, profissional e data para carregar os horários.";
            return;
        }
        timeSelect.disabled = true;
        timeHelp.textContent = "Carregando horários disponíveis…";
        announce(timeHelp.textContent);
        const params = new URLSearchParams({servico: service.value, profissional: professional.value, data: dateInput.value});
        try {
            const response = await fetch(`${form.dataset.horariosUrl}?${params}`, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok) throw new Error();
            const data = await response.json();
            timeSelect.innerHTML = '<option value="">Selecione um horário</option>';
            data.horarios.forEach((item) => timeSelect.add(new Option(item.texto, item.valor, false, item.valor === previous)));
            renderTimes(data.horarios, previous);
            timeHelp.textContent = data.horarios.length ? "Escolha um dos horários abaixo." : "Não há horários disponíveis nessa data. Tente outro dia.";
            announce(timeHelp.textContent);
        } catch (_) {
            timeOptions.innerHTML = "";
            timeHelp.textContent = "Não foi possível carregar os horários. Tente novamente.";
            announce(timeHelp.textContent);
        } finally {
            timeSelect.disabled = false;
        }
    }

    function updateSummary() {
        const service = checked(serviceInputs)?.closest("label")?.querySelector("strong")?.textContent || "—";
        const professional = checked(professionalInputs)?.closest("label")?.querySelector("strong")?.textContent || "—";
        const date = dateInput.value ? new Date(`${dateInput.value}T12:00:00`).toLocaleDateString("pt-BR") : "—";
        document.querySelector('[data-summary="service"]').textContent = service;
        document.querySelector('[data-summary="professional"]').textContent = professional;
        document.querySelector('[data-summary="datetime"]').textContent = timeSelect.value ? `${date} às ${timeSelect.value}` : date;
    }

    [...serviceInputs, ...professionalInputs].forEach((input) => input.addEventListener("change", loadTimes));
    dateInput.addEventListener("change", loadTimes);
    form.addEventListener("submit", () => {
        if (!submit || submit.disabled) return;
        submit.disabled = true;
        submit.querySelector("span").textContent = "Agendando…";
        announce("Enviando seu agendamento.");
    });
    phone?.addEventListener("input", () => {
        const digits = phone.value.replace(/\D/g, "").slice(0, 11);
        if (digits.length <= 2) phone.value = digits;
        else if (digits.length <= 6) phone.value = `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
        else if (digits.length <= 10) phone.value = `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
        else phone.value = `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    });
    showStep(currentStep);
    loadTimes();
}());
