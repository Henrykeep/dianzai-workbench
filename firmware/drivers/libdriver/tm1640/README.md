[English](/README.md) | [ 简体中文](/README_zh-Hans.md) | [繁體中文](/README_zh-Hant.md) | [日本語](/README_ja.md) | [Deutsch](/README_de.md) | [한국어](/README_ko.md)

<div align=center>
<img src="/doc/image/logo.svg" width="400" height="150"/>
</div>

## LibDriver TM1640

[![MISRA](https://img.shields.io/badge/misra-compliant-brightgreen.svg)](/misra/README.md) [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://www.libdriver.com/docs/tm1640/index.html) [![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)](/LICENSE)

TM1640 is a LED (Light Emitting Diode Display) drive control circuit integrating MCU digital interface, digital latch, LED high voltage drive circuit, etc. The product has excellent performance and reliable quality, and is mainly applied in display drive for electronic scales and other small home appliances.

LibDriver TM1640 is a full-featured driver for TM1640, launched by LibDriver. It provides digital tube display and additional features. LibDriver is MISRA compliant.

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

/src includes LibDriver TM1640 source files.

/interface includes LibDriver TM1640 GPIO platform independent template.

/test includes LibDriver TM1640 driver test code and this code can test the chip necessary function simply.

/example includes LibDriver TM1640 sample code.

/doc includes LibDriver TM1640 offline document.

/datasheet includes TM1640 datasheet.

/project includes the common Linux and MCU development board sample code. All projects use the shell script to debug the driver and the detail instruction can be found in each project's README.md.

/misra includes the LibDriver MISRA code scanning results.

### Install

Reference /interface GPIO platform independent template and finish your platform GPIO driver.

Add the /src directory, the interface driver for your platform, and your own drivers to your project, if you want to use the default example drivers, add the /example directory to your project.

### Usage

You can refer to the examples in the /example directory to complete your own driver. If you want to use the default programming examples, here's how to use them.

#### example basic

```C
#include "driver_tm1640_basic.h"

uint8_t res;
uint8_t number[] = {TM1640_NUMBER_0, TM1640_NUMBER_1, TM1640_NUMBER_2,
                    TM1640_NUMBER_3, TM1640_NUMBER_4, TM1640_NUMBER_5,
                    TM1640_NUMBER_6, TM1640_NUMBER_7, TM1640_NUMBER_8, TM1640_NUMBER_9};

/* init */
res = tm1640_basic_init();
if (res != 0)
{
    return 1;
}

...
    
/* write */
res = tm1640_basic_write(0x00, number, 8);
if (res != 0)
{
    (void)tm1640_basic_deinit();
    
    return 1;
}

...
    
/* on */
res = tm1640_basic_display_on();
if (res != 0)
{
    (void)tm1640_basic_deinit();
    
    return 1;
}

...
    
/* off */
res = tm1640_basic_display_off();
if (res != 0)
{
    (void)tm1640_basic_deinit();
    
    return 1;
}

...
    
/* deinit */
res = tm1640_basic_deinit();
if (res != 0)
{
    return 1;
}

return 0;
```

### Document

Online documents: [https://www.libdriver.com/docs/tm1640/index.html](https://www.libdriver.com/docs/tm1640/index.html).

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