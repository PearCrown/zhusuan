"""
电路模拟器：对给定的门列表和连线进行拓扑排序 + 逐门求值。
支持组件：NAND, AND, OR, NOT, XOR, NOR
门的端口约定：
  - 输入端口名：in1, in2 （单输入门只有 in1）
  - 输出端口名：out
"""

from collections import defaultdict, deque

GATE_TYPES = {"NAND", "AND", "OR", "NOT", "XOR", "NOR"}


def _gate_eval(gate_type, inputs):
    """inputs 是 list[int]，返回 0/1"""
    if gate_type == "NAND":
        a, b = inputs[0], inputs[1]
        return 0 if (a and b) else 1
    if gate_type == "AND":
        a, b = inputs[0], inputs[1]
        return 1 if (a and b) else 0
    if gate_type == "OR":
        a, b = inputs[0], inputs[1]
        return 1 if (a or b) else 0
    if gate_type == "NOT":
        return 1 - inputs[0]
    if gate_type == "XOR":
        a, b = inputs[0], inputs[1]
        return 1 if (a ^ b) else 0
    if gate_type == "NOR":
        a, b = inputs[0], inputs[1]
        return 0 if (a or b) else 1
    raise ValueError(f"未知门类型: {gate_type}")


def simulate(puzzle, gates, wires, input_values):
    """
    运行一次电路模拟。
    :param puzzle:  谜题定义（含 inputs/outputs 名称）
    :param gates:   [{"id": "g1", "type": "NAND", ...}]
    :param wires:   [{"from": {"gateId": "g1", "port": "out"}, "to": {"gateId": "g2", "port": "in1"}}]
    :param input_values:  [0, 1, ...] 顺序对应 puzzle["inputs"]
    :return: list[int] 输出值，顺序对应 puzzle["outputs"]
    """
    # 构建门字典
    gate_map = {g["id"]: g for g in gates}

    # 每个门的输入值缓存  {gateId: {portName: 0/1}}
    gate_inputs = defaultdict(dict)
    # 每个门的输出缓存
    gate_outputs = {}

    # 输入端点：每个输入作为一个"虚拟门"，id 用 "__in_A"
    virtual_inputs = {}
    for i, name in enumerate(puzzle["inputs"]):
        vid = f"__in_{name}"
        virtual_inputs[vid] = input_values[i]

    # 反向连线索引：to -> from （哪个输入端口连到哪个输出）
    # key: (gateId, port)  value: (gateId or '__in_X', port or None)
    connections = {}
    for w in wires:
        to_gate = w["to"]["gateId"]
        to_port = w["to"]["port"]
        from_gate = w["from"]["gateId"]
        from_port = w["from"].get("port", "out")
        connections[(to_gate, to_port)] = (from_gate, from_port)

    # 拓扑排序
    # 入度 = 门的未连接输入端口数 + 连线来源门的入度依赖……
    # 简化：BFS 拓扑——每个门必须等它所有输入来源算完
    # 入度计数：一个门的入度 = 它有多少输入端口已被连线（等来源算完）
    in_degree = defaultdict(int)
    dependents = defaultdict(list)  # from -> [to gates]

    for gate in gates:
        gid = gate["id"]
        gtype = gate["type"]
        num_inputs = 1 if gtype == "NOT" else 2
        # 看看这个门的每个输入端口
        for port_idx in range(num_inputs):
            port_name = f"in{port_idx + 1}"
            if (gid, port_name) in connections:
                in_degree[gid] += 1
                from_gate, _ = connections[(gid, port_name)]
                dependents[from_gate].append(gid)
            else:
                # 输入悬空，当 0 处理
                gate_inputs[gid][port_name] = 0

    queue = deque()
    for gate in gates:
        gid = gate["id"]
        if in_degree[gid] == 0:
            queue.append(gid)
    for vid in virtual_inputs:
        queue.append(vid)

    computed = set()

    def get_val(from_gate, from_port):
        """取得某个来源的输出值"""
        if from_gate in virtual_inputs:
            return virtual_inputs[from_gate]
        if from_gate in gate_outputs:
            return gate_outputs[from_gate]
        raise RuntimeError(f"来源 {from_gate} 尚未计算")

    while queue:
        current = queue.popleft()
        if current in computed:
            continue
        computed.add(current)

        if current in virtual_inputs:
            val = virtual_inputs[current]
        else:
            gate = gate_map[current]
            gtype = gate["type"]
            num_inputs = 1 if gtype == "NOT" else 2
            vals = []
            for port_idx in range(num_inputs):
                port_name = f"in{port_idx + 1}"
                if (current, port_name) in connections:
                    from_gate, from_port = connections[(current, port_name)]
                    v = get_val(from_gate, from_port)
                else:
                    v = 0
                vals.append(v)
            val = _gate_eval(gtype, vals)
            gate_outputs[current] = val

        # 更新依赖
        for dep in dependents[current]:
            in_degree[dep] -= 1
            if in_degree[dep] <= 0:
                queue.append(dep)

    # 提取输出
    results = []
    for out_name in puzzle["outputs"]:
        out_gate_id = f"__out_{out_name}"
        # 找到连接到这个输出端点的来源
        found = None
        for (to_gate, to_port), (from_gate, from_port) in connections.items():
            if to_gate == out_gate_id:
                found = (from_gate, from_port)
                break
        if found is None:
            results.append(0)
        else:
            results.append(get_val(*found))
    return results
