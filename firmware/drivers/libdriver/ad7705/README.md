[English](/README.md) | [ 简体中文](/README_zh-Hans.md) | [繁體中文](/README_zh-Hant.md) | [日本語](/README_ja.md) | [Deutsch](/README_de.md) | [한국어](/README_ko.md)

<div align=center>
<img src="/doc/image/logo.svg" width="400" height="150"/>
</div>

## LibDriver AD7705

[![MISRA](https://img.shields.io/badge/misra-compliant-brightgreen.svg)](/misra/README.md) [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://www.libdriver.com/docs/ad7705/index.html) [![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](/LICENSE)

The AD7705 are complete analog front ends for low frequency measurement applications. These 2-/3-channel devices can accept low level input signals directly from a transducer and produce serial digital output. The devices employ a Σ-Δ conversion technique to realize up to 16 bits of no missing codes performance. The selected input signal is applied to a proprietary, programmable-gain front end based around an analog modulator. The modulator output is processed by an on chip digital filter. The first notch of this digital filter can be programmed via an on-chip control register, allowing adjustment of the filter cutoff and output update rate. 

LibDriver AD7705 is a full-featured driver for AD7705, launched by LibDriver.It provides ADC reading and additional features. LibDriver is MISRA compliant.

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

/src includes LibDriver AD7705 source files.

/interface includes LibDriver AD7705 SPI platform independent template.

/test includes LibDriver AD7705 driver test code and this code can test the chip necessary function simply.

/example includes LibDriver AD7705 sample code.

/doc includes LibDriver AD7705 offline document.

/datasheet includes AD7705 datasheet.

/project includes the common Linux and MCU development board sample code. All projects use the shell script to debug the driver and the detail instruction can be found in each project's README.md.

/misra includes the LibDriver MISRA code scanning results.

### Install

Reference /interface SPI platform independent template and finish your platform SPI driver.

Add the /src directory, the interface driver for your platform, and your own drivers to your project, if you want to use the default example drivers, add the /example directory to your project.

### Usage

You can refer to the examples in the /example directory to complete your own driver. If you want to use the default programming examples, here's how to use them.

#### example basic

```C
#include "driver_ad7705_basic.h"

uint8_t res;
uint32_t i;

/* init */
res = ad7705_basic_init(AD7705_CHANNEL_AIN1_POSITIVE_AIN1_NEGATIVE);
if (res != 0)
{
    return 1;
}

...
    
/* loop */
for (i = 0; i < 3; i++)
{
    uint16_t raw;
    float volt;

    /* read data */
    res = ad7705_basic_read(&raw, &volt);
    if (res != 0)
    {
        (void)ad7705_basic_deinit();

        return 1;
    }

    /* output */
    ad7705_interface_debug_print("%d/%d %0.5fV.\n", i + 1, 3, volt);

    /* delay 1000ms */
    ad7705_interface_delay_ms(1000);
    
    ...
}

...
    
/* deinit */
(void)ad7705_basic_deinit();

return 0;
```

### Document

Online documents: [https://www.libdriver.com/docs/ad7705/index.html](https://www.libdriver.com/docs/ad7705/index.html).

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