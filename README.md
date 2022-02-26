# OctoPrint Simple Chamber

Simple chamber temperature controller: run fan if chamber temperature is higher than a certain value.

Chamber temperature is automatically displayed in the `Temperature` tab.

## Installation

Install manually using this [archive URL](https://github.com/adrcunha/OctoPrint-SimpleChamber/archive/master.zip):

	https://github.com/adrcunha/OctoPrint-SimpleChamber/archive/master.zip

## Configuration

Chamber temperature is measured by a DHT11/DHT22 sensor conhected to a GPIO pin defined in the settings.

Fan is controlled through PI + PWM via a GPIO pin defined in the settings.

Max temperature (in Celsius) is also defined in the settings.

## Acknowledgements

Inspired by (sometimes pretty strongly):

* [OctoPrint-PlotlyTempGraph sample](https://github.com/jneilliii/OctoPrint-PlotlyTempGraph/blob/master/klipper_additional_temp.py)
* [Andreas Spiess' video #138](https://www.sensorsiot.org/variable-speed-cooling-fan-for-raspberry-pi-using-pwm-video138/)
* [OctoPrint-EmailNotifier plugin](https://github.com/adrcunha/OctoPrint-EmailNotifier)
* [OctoLight Plugin](https://github.com/adrcunha/OctoLight)

## License

Licensed under the terms of the [AGPLv3](http://opensource.org/licenses/AGPL-3.0).
