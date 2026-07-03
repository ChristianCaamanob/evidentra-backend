# EJEMPLO INTENCIONALMENTE MALO (para self-test del check G2).
def generar_briefing(client, estudiante):
    prompt = f"Analiza a {estudiante['nombre']} (RUT {estudiante['rut']})"
    return client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt, "email": estudiante["email"]}],
    )
