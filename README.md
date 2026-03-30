# Hierarchical Colored Petri Net (HCPN) Generation from IoT Logs

This repository provides source code to **generate Hierarchical Colored Petri Nets (HCPNs)** from **sensor, actuator, and interaction logs**.

---

## Prerequisites

Before running the code, ensure you have the following:

- **Sensor, actuator, and interaction logs**  
  - Example log file: `bridge_traffic_simulation_noisy.csv`  

- **cpn-py**  
  - We have extended functions of [cpn-py](https://github.com/fit-alessandro-berti/cpn-py) to support loading Colored Petri Nets from event logs.  

- **pm4py**  
  - Slightly modified to work with our HCPN generation process.  

---

## Execution Steps

Run the Python scripts **in the following order**:

1. **`IoTLog2EventLog.py`**  
   - Converts sensor, actuator, and interaction logs into **event logs**.  

2. **`EventLog2HCPN.py`**  
   - Converts event logs into **HCPNs**.  

3. **`Conformance_checking.py`**  
   - Performs **conformance checking** on the generated HCPNs and visualises the results.  

---

## Example Output

- `\cpn_new1\_I_E1_E2_W1.cpn` – Example of a generated HCPN.
- This example corresponds to the **lighting system on a bridge road**.
- **E1** and **E2** refer to controller light poles at the **entrance** and **exit**, respectively.
- **W1** refers to **worker light poles**.
