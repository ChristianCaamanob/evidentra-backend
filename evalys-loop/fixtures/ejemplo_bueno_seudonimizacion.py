# EJEMPLO CORRECTO: solo viaja el seudonimo.
def generar_briefing(client, seudonimo, respuestas):
    prompt = f"Analiza a {seudonimo} con estas respuestas: {respuestas}"
    return client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
