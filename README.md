# PipelineWelding
关于管道焊接的大模型

## 工程目录

```text
PipelineWelding/    
├── configs/
│   ├── agent_config.yaml              # 智能体行为配置
│   ├── model_config.yaml              # 模型供应商、模型名、温度、重试等配置
│   └── welding_required_fields.yaml   # 焊接缺陷重问必填字段 schema
├── prompts/
│   └── welding_reask_agent_prompt.md  # 大模型系统提示词
├── src/
│   └── pipeline_welding/
│       ├── agents/
│       │   └── welding_reask_agent.py # 缺陷重问智能体核心逻辑
│       └── config/
│           └── loader.py              # YAML 配置加载工具
├── demo_reask.py                      # 本地演示脚本
├── requirements.txt                   # 运行依赖
├── pyproject.toml                     # Python 工程打包配置
├── .env.example                       # 环境变量模板
└── README.md
```

## 缺陷重问智能体

当前仓库提供了一个轻量的焊接缺陷重问智能体，用于在缺陷分析前检查关键工艺信息是否齐全。若信息缺失或枚举字段不在支持范围内，智能体会返回中文追问提示。

### 必填字段

| 字段 key | 中文名称 | 要求 |
| --- | --- | --- |
| `welding_process` | 焊接工艺 | `SMAW` / `GTAW` / `GMAW` / `FCAW` / `SAW`，支持 `GTAW+SMAW` 这类组合 |
| `welding_object` | 焊接对象 | 管道、板材、管件、设备 |
| `joint_type` | 接头形式 | 对接、角接、搭接、支管连接 |
| `base_material` | 母材牌号/规格 | 来自材料数据库、标准材料分组、材质证明书或设计文件 |
| `base_thickness_or_diameter` | 母材厚度/管径 | 来自图纸、材料清单、标准适用范围 |

### 运行示例

```powershell
pip install -r .\requirements.txt
pip install -e .
python .\demo_reask.py
```

### 代码调用

```python
from pipeline_welding.agents import build_default_agent

agent = build_default_agent()
result = agent.inspect({
    "welding_process": "SMAW",
    "welding_object": "管道",
    "joint_type": "",
    "base_material": "ASTM A106 Gr.B",
})

print(result["complete"])
print(result["message"])
```

### 智能体 Prompt

如果要接入大模型工作流，可以直接使用 [prompts/welding_reask_agent_prompt.md](prompts/welding_reask_agent_prompt.md) 作为前置重问智能体的系统提示词。

### 配置文件说明

| 文件 | 作用 |
| --- | --- |
| `configs/model_config.yaml` | 单列模型配置，包括模型供应商、模型名、温度、最大 token、超时、重试和 API 环境变量名 |
| `configs/agent_config.yaml` | 智能体行为配置，包括 Prompt 路径、是否缺失重问、是否非法枚举重问、输出格式 |
| `configs/welding_required_fields.yaml` | 焊接业务字段配置，包括焊接工艺、焊接对象、接头形式、母材牌号/规格、母材厚度/管径 |
| `.env.example` | 环境变量模板，不提交真实密钥 |
| `requirements.txt` | 项目运行依赖 |
