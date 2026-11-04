[English](/README.md) | [ 简体中文](/README_zh-Hans.md) | [繁體中文](/README_zh-Hant.md) | [日本語](/README_ja.md) | [Deutsch](/README_de.md) | [한국어](/README_ko.md)

<div align=center>
<img src="/doc/image/logo.svg" width="400" height="150"/>
</div>

## LibDriver TLC5615

[![MISRA](https://img.shields.io/badge/misra-compliant-brightgreen.svg)](/misra/README.md) [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://www.libdriver.com/docs/tlc5615/index.html) [![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](/LICENSE)

The TLC5615 is a 10-bit voltage output digital-to-analog converter (DAC) with a buffered reference input (high impedance). The DAC has an output voltage range that is two times the reference voltage, and the DAC is monotonic. The device is simple to use, running from a single supply of 5V. A power-on-reset function is incorporated to ensure repeatable start-up conditions.

LibDriver TLC5615 is a full-featured driver for TLC5615, launched by LibDriver. It provides DAC output writing, and additional features. LibDriver is MISRA compliant.

### Table of Contents

  - [Instruction](#Instruction)
  - [Install](#Install)
  - [Usage](#Usage)
    - [example basic](#example-basic)
  - [Document](#Document)
  - [Contributing](#Contributing)
  - [License](#License)
  - [Contact Us](#Contact-Us)

### Instruction

/src includes LibDriver TLC5615 source files.

/interface includes LibDriver TLC5615 SPI platform independent template.

/test includes LibDriver TLC5615 driver test code and this code can test the chip necessary function simply.

/example includes LibDriver TLC5615 sample code.

/doc includes LibDriver TLC5615 offline document.

/datasheet includes TLC5615 datasheet.

/project includes the common Linux and MCU development board sample code. All projects use the shell script to debug the driver and the detail instruction can be found in each project's README.md.

/misra includes the LibDriver MISRA code scanning results.

### Install

Reference /interface SPI platform independent template and finish your platform SPI driver.

Add the /src directory, the interface driver for your platform, and your own drivers to your project, if you want to use the default example drivers, add the /example directory to your project.

### Usage

You can refer to the examples in the /example directory to complete your own driver. If you want to use the default programming examples, here's how to use them.

#### example basic

```C
#include "driver_tlc5615_basic.h"

uint8_t res;
float dac = 1.0f;
float ref = 2.048f;

/* init */
res = tlc5615_basic_init(ref);
if (res != 0)
{
    return 1;
}

...
    
/* output */
tlc5615_interface_debug_print("tlc5615: reference voltage is %.03fV.\n", ref);
tlc5615_interface_debug_print("tlc5615: dac is %.03fV.\n", dac);

/* write data */
res = tlc5615_basic_write(dac);
if (res != 0)
{
    (void)tlc5615_basic_deinit();

    return 1;
}

...
    
/* close the chip */
res = tlc5615_basic_deinit();
if (res != 0)
{
    return 1;
}

return 0;
```

### Document

Online documents: [https://www.libdriver.com/docs/tlc5615/index.html](https://www.libdriver.com/docs/tlc5615/index.html).

Offline documents: /doc/html/index.html.

### Contributing

Please refer to CONTRIBUTING.md.

### License

Copyright (c) 2015 - present LibDriver All rights reserved



The MIT License (MIT) 



Permission is hereby granted, free of charge, to any person obtaining a copy

of this software and associated documentation files (the "Software"), to deal

in the Software without restriction, including without limitation the rights

to use, copy, modify, merge, publish, distribute, sublicense, and/or sell

copies of the Software, and to permit persons to whom the Software is

furnished to do so, subject to the following conditions: 



The above copyright notice and this permission notice shall be included in all

copies or substantial portions of the Software. 



THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR

IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,

FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE

AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER

LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,

OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE

SOFTWARE. 

### Contact Us

Please send an e-mail to lishifenging@outlook.com.