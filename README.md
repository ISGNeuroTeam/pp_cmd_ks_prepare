# pp_cmd_ks_prepare
Postprocessing command "ks_prepare"

Usage example:
`dtcd_read_graph test | ks_prepare  ControlledRichLabelNode01_4i`

## Getting started
###  Prerequisites
1. [Miniconda](https://docs.conda.io/en/latest/miniconda.html)

### Installing
1. Create virtual environment with post-processing sdk 
```bash
make dev
```

2. Configure connection to platform in `config.ini` to set mapping between objects and primitiveName  
Example:  
```ini
[objects]
pad = UncontrolledRichLabelNode31
well = ControlledRichLabelNode01
pipe = StepRichLabelNode22
dns = TargetRichLabelNode2
junctionpoint = UncontrolledRichLabelNode11
```

