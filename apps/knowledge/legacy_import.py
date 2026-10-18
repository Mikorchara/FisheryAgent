"""One-time legacy JSON conversion; never loaded by the management content service."""

def chunk_knowledge(kg: dict) -> list[dict]:
    """Preserve the original legacy chunk IDs, text and keywords."""
    chunks: list[dict] = []
    for key, data in kg["water_quality"].items():
        unit = data.get("unit", "")
        safe = data.get("optimal_range", data.get("safe_range", []))
        guidance = data.get("guidance", {})
        body = f"水质参数 {key}：适宜范围 {safe[0]}-{safe[1]}{' ' + str(unit) if unit else ''}。"
        if guidance:
            body += " " + " ".join(f"{k}: {v}" for k, v in guidance.items())
        chunks.append({"id": f"wq_{key}", "type": "water_quality", "text": body, "keywords": [key]})

    for stage in kg["life_cycle"]["stages"]:
        kp = stage.get("key_params", {})
        params_text = "；".join(f"{k}: {v}" for k, v in kp.items()) if kp else ""
        parts = [f"鳗鲡生长阶段：{stage['name']}"]
        for field, label in (("size", "规格"), ("duration", "周期"), ("habitat", "环境"), ("note", "备注")):
            if stage.get(field):
                parts.append(f"{label}：{stage[field]}")
        body = "。".join(parts) + "。" + params_text
        chunks.append({"id": f"stage_{stage['name']}", "type": "life_cycle", "text": body,
                       "keywords": [stage["name"]]})

    for disease in kg["diseases"]:
        body = (
            f"病害：{disease['name']}。病原体：{disease['pathogen']}。"
            f"症状：{'、'.join(disease['symptoms'])}。"
            f"高发条件：{'、'.join(disease['triggers'])}。"
            f"治疗：{'；'.join(disease['treatment'])}。"
            f"预防：{'；'.join(disease['prevention'])}。"
        )
        chunks.append({"id": f"disease_{disease['name']}", "type": "disease", "text": body,
                       "keywords": disease["symptoms"] + disease["triggers"]})

    feeding = kg["feeding_management"]
    chunks.append({"id": "feeding_rate", "type": "feeding", "text": "投喂率与水温关系：" + "；".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in feeding["feeding_rate_by_temperature"].items()),
        "keywords": ["投喂", "水温", "饲料"]})
    chunks.append({"id": "feeding_principles", "type": "feeding", "text": "投喂原则：" + "；".join(
        feeding["key_principles"]), "keywords": ["投喂", "原则"]})
    chunks.append({"id": "feeding_freq", "type": "feeding", "text": "投喂频率：" + "；".join(
        f"{k}: {v}" for k, v in feeding["feeding_frequency"].items()), "keywords": ["投喂", "频率"]})

    environment = kg["environmental_management"]
    for key in ("water_exchange", "aeration", "light_management", "stocking_density", "grading"):
        data = environment[key]
        body = f"{key}："
        if isinstance(data, dict):
            body += "；".join(f"{k}: {v}" for k, v in data.items() if k != "method")
            if "method" in data:
                body += "。方法：" + "、".join(data["method"])
        else:
            body += str(data)
        chunks.append({"id": f"env_{key}", "type": "environment", "text": body, "keywords": [key]})

    for name, problem in kg["common_problems"].items():
        body = (f"常见问题 {name}：可能原因——{'、'.join(problem['causes'])}。"
                f"处理措施——{'；'.join(problem['actions'])}。")
        chunks.append({"id": f"problem_{name}", "type": "problem", "text": body,
                       "keywords": problem["causes"]})

    relationships = kg["key_relationships"]
    chunks.append({"id": "relationships", "type": "relationships", "text": "水质耦合关系：" + "；".join(
        f"{k}: {v}" for k, v in relationships.items()), "keywords": list(relationships.keys())})
    return chunks


