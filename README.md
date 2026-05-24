# PipelineWelding
关于管道焊接的大模型

## 工程目录

```text
PipelineWelding/
├── configs/
│   ├── agent_config.yaml              # 智能体行为配置
│   ├── model_config.yaml              # 模型供应商、模型名、温度、重试等配置
│   ├── welding_required_fields.yaml   # 焊接缺陷重问必填字段 schema
│   ├── welding_standard_agent_config.yaml # 标准制定智能体配置
│   └── welding_document_agent_config.yaml # 文档生成智能体配置
├── prompts/
│   ├── welding_reask_agent_prompt.md  # 缺陷重问智能体系统提示词
│   ├── welding_standard_agent_prompt.md # 标准制定智能体系统提示词
│   └── welding_document_agent_prompt.md # 文档生成智能体系统提示词
├── src/
│   └── pipeline_welding/
│       ├── agents/
│       │   ├── welding_reask_agent.py # 缺陷重问智能体核心逻辑
│       │   ├── welding_standard_agent.py # 标准制定智能体核心逻辑
│       │   └── welding_document_agent.py # 标准文档生成智能体核心逻辑
│       ├── graphs/
│       │   └── welding_reask_graph.py # LangGraph State 对话流程
│       ├── documents/
│       │   └── docx_reader.py         # DOCX 参考文档读取
│       ├── mcp/
│       │   └── search_client.py       # MCP 搜索客户端适配器
│       └── config/
│           └── loader.py              # YAML 配置加载工具
├── data/
│   └── MHPWPS-062.docx                # 本地 WPS 参考文件
├── demo_reask.py                      # 本地演示脚本
├── demo_standard_agent.py             # 标准制定智能体演示脚本
├── demo_document_agent.py             # 文档生成智能体演示脚本
├── requirements.txt                   # 运行依赖
├── pyproject.toml                     # Python 工程打包配置
├── .env.example                       # 环境变量模板
└── README.md
```

## 缺陷重问智能体

当前仓库提供了一个基于 LangGraph State 的焊接缺陷重问智能体，用于在缺陷分析前检查关键工艺信息是否齐全。若信息缺失或枚举字段不在支持范围内，智能体会返回中文追问提示。

对话流程最多支持五轮问答。每轮会把已经满足的信息存入 State，并在下一轮自动带入继续补全。信息完整后会输出 `complete_case` 字典格式；如果五轮后仍不完整，也会输出当前已收集到的 `complete_case`。

在 `demo_reask.py` 中，当前置重问智能体判定信息完整，或五轮问答结束后，程序会自动把当前 State 中的 JSON 字段传递给标准制定智能体。标准制定智能体会以这些字段作为已知条件，通过 MCP 查询 `data/MHPWPS-062.docx` 模板中需要填充的信息，并返回包含 `document_fields` 的 JSON。随后文档生成智能体会使用 `document_fields` 按模板表格和段落字段一一对应填充，查询不到的字段写 `/`，并输出 `.docx` 到 `result/`。

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

启动后可以像对话一样输入：

```text
用户 第 1 轮> 工艺 GTAW+SMAW，焊接对象是管道
Agent>
信息不完整，请补充以下信息：
1. 请补充【接头形式】。建议来源：焊接接头详图、坡口图或施工图。 可选值：对接 / 角接 / 搭接 / 支管连接。 示例：对接、支管连接。
2. 请补充【母材牌号/规格】。建议来源：材料数据库、标准材料分组、材质证明书或设计文件。 示例：20#、Q345R、ASTM A106 Gr.B / P-No.1。
3. 请补充【母材厚度/管径】。建议来源：图纸、材料清单、标准适用范围。 示例：壁厚 8 mm，DN100、板厚 12 mm、OD 219.1 x 8.2 mm。

用户 第 2 轮> 接头对接，母材 ASTM A106 Gr.B / P-No.1，OD 219.1 x 8.2 mm
Agent>
信息完整，可以继续进行缺陷判断。
complete_case = {
    "welding_process": "GTAW+SMAW",
    "welding_object": "管道",
    "joint_type": "对接",
    "base_material": "ASTM A106 Gr.B / P-No.1",
    "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
}

正在将当前焊接 JSON 信息传递给标准制定智能体，并执行 MCP 查询...
{
  "document_fields": {
    "wps_no": "/",
    "pqr_no": "/",
    "welding_process": "GTAW+SMAW",
    "mechanization": "手工",
    "groove_type": "对接",
    "base_material_grade": "ASTM A106 Gr.B / P-No.1",
    "pipe_diameter_thickness_butt": "OD 219.1 x 8.2 mm",
    "current": "/",
    "voltage": "/"
  }
}
已生成焊接标准文档：F:\pipeline\PipelineWelding\result\welding_standard_filled_20260524_120000.docx
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

### LangGraph 调用

```python
from pipeline_welding.graphs import build_welding_reask_graph, create_initial_state

graph = build_welding_reask_graph()
state = create_initial_state()

state["latest_user_input"] = "工艺 GTAW+SMAW，焊接对象是管道"
state = graph.invoke(state)

state["latest_user_input"] = "接头对接，母材 ASTM A106 Gr.B，OD 219.1 x 8.2 mm"
state = graph.invoke(state)

print(state["complete"])
print(state["assistant_message"])
```

### 智能体 Prompt

如果要接入大模型工作流，可以直接使用 [prompts/welding_reask_agent_prompt.md](prompts/welding_reask_agent_prompt.md) 作为前置重问智能体的系统提示词。

## 管道焊接标准制定智能体

标准制定智能体只接收 `welding_reask_agent` 已汇总出的 JSON 信息，然后读取本地 WPS 参考文件 [data/MHPWPS-062.docx](data/MHPWPS-062.docx)，再通过 MCP 协议连接外部搜索引擎查询相关标准资料，最终只打印并返回模板可填字段：

```json
{
  "document_fields": {
    "welding_process": "GTAW+SMAW",
    "groove_type": "对接",
    "base_material_grade": "ASTM A106 Gr.B / P-No.1",
    "pipe_diameter_thickness_butt": "OD 219.1 x 8.2 mm",
    "preheat_temperature": "/"
  }
}
```

`reference`、`mcp_search`、`pipeline_welding_standard` 等过程信息不会进入最终返回；无法确定的字段统一为 `/`。

本地演示：

```powershell
python .\demo_standard_agent.py
```

代码调用：

```python
from pathlib import Path

from pipeline_welding.agents import build_welding_standard_agent_from_config
from pipeline_welding.config import load_yaml_config

config = load_yaml_config(Path("configs/welding_standard_agent_config.yaml"))
agent = build_welding_standard_agent_from_config(config)
result = agent.build_standard({
    "welding_process": "GTAW+SMAW",
    "welding_object": "管道",
    "joint_type": "对接",
    "base_material": "ASTM A106 Gr.B / P-No.1",
    "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
})
```

如需启用 MCP 外部搜索，需要在 [configs/welding_standard_agent_config.yaml](configs/welding_standard_agent_config.yaml) 中配置 MCP server 的 `transport`、`tool_name` 和 `url`，并在 `.env` 中配置 Tavily API Key。

当前项目默认使用 Tavily 官方远程 MCP Server：

```yaml
mcp_search:
  enabled: true
  transport: streamable_http
  tool_name: tavily_search
  command: ""
  args: []
  url: https://mcp.tavily.com/mcp/?tavilyApiKey=${TAVILY_API_KEY}
  max_results: 5
```

运行 `python .\demo_standard_agent.py` 时，MCP Client 会直接连接 Tavily 在线 MCP Server。`.env` 中只需要填写：

```env
TAVILY_API_KEY=replace-with-your-tavily-api-key
TAVILY_SEARCH_DEPTH=basic
```

## 焊接标准文档生成智能体

文档生成智能体接收 `welding_standard_agent` 返回的 JSON，读取 [data/MHPWPS-062.docx](data/MHPWPS-062.docx) 作为模板，保留原有表头和表格结构，只填充能明确映射的信息。MCP 搜索结果只作为字段参考，不会直接追加到文档末尾，也会过滤 `Not found`、`Unknown tool`、`Unknown too` 等错误内容。

单独演示：

```powershell
python .\demo_document_agent.py
```

输出目录：

```text
result/
```

### 配置文件说明

| 文件 | 作用 |
| --- | --- |
| `configs/model_config.yaml` | 单列模型配置，包括模型供应商、模型名、温度、最大 token、超时、重试和 API 环境变量名 |
| `configs/agent_config.yaml` | 智能体行为配置，包括 Prompt 路径、是否缺失重问、是否非法枚举重问、输出格式 |
| `configs/welding_required_fields.yaml` | 焊接业务字段配置，包括焊接工艺、焊接对象、接头形式、母材牌号/规格、母材厚度/管径 |
| `configs/welding_standard_agent_config.yaml` | 标准制定智能体配置，包括 WPS 文档路径和 MCP 搜索连接参数 |
| `configs/welding_document_agent_config.yaml` | 文档生成智能体配置，包括模板 DOCX 路径、输出目录和文件名前缀 |
| `.env.example` | 环境变量模板，不提交真实密钥 |
| `requirements.txt` | 项目全部依赖，包括运行、测试和代码检查依赖 |
