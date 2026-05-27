# MATSim Melbourne Baseline scenario

This repository contains the baseline scenario for the MATSim Melbourne model. The code in this repository uses the outputs of the [network](https://github.com/matsim-melbourne/network) and [demand](https://github.com/matsim-melbourne/demand) generation algorithms as its inputs.

This reconstruction targets the latest MATSim release line and uses Java 25.

Use the project scripts for the local workflow:

```bash
./scripts/bootstrap_baseline.sh
./scripts/normalize_baseline_inputs.sh
./scripts/run_baseline_scenario.sh
```

For `M3` workflow:

You need to edit `build.sh` with the correct M3 username.

`./build.sh`


To `hot start` a plan, you will need to edit `scenario/v1/config.xml` with

```yaml
<param name="inputPlansFile" value="./output/output_plans.xml.gz" />
```

To use previously calculate plan, and update first iteration in config.

```yaml
<module name="controler">
    <param name="firstIteration" value="501" />
    <param name="lastIteration" value="1000" />
</module>
```

## Publications
- Jafari, A., Singh, D., Both, A., Abdollahyar, M., Gunn, L., Pemberton, S., & Giles-Corti, B. (2024). Activity-based and agent-based transport model of Melbourne: an open multi-modal transport simulation model for Greater Melbourne. Journal of Intelligent Transportation Systems, 1-18. [https://doi.org/10.1080/15472450.2024.2372894](https://www.tandfonline.com/doi/full/10.1080/15472450.2024.2372894)
- Jafari, A., Singh, D., Both, A. (2021). [Towards a MATSim model for active transportation in Melbourne](https://cloudstor.aarnet.edu.au/plus/s/iIH5MvGkQR2wdI2), *MATSim User Meeting* [\[video recording\]](https://video.ethz.ch/events/2021/mum/ccac67cd-fb1d-4726-a43d-bea75fb9ea42.html)
