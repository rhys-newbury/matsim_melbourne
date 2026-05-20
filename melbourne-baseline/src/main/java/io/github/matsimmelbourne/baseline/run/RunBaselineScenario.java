package io.github.matsimmelbourne.baseline.run;

/*-
 * #%L
 * Example Project
 * %%
 * Copyright (C) 2020 - 2026 by its authors.
 * %%
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Lesser Public License for more details.
 *
 * You should have received a copy of the GNU General Lesser Public
 * License along with this program.  If not, see
 * <http://www.gnu.org/licenses/lgpl-3.0.html>.
 * #L%
 */

import ch.sbb.matsim.mobsim.qsim.SBBTransitModule;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkWriter;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.network.algorithms.MultimodalNetworkCleaner;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.config.groups.RoutingConfigGroup;
import java.io.IOException;
import java.util.Set;

public class RunBaselineScenario {
    private final Config config;
    private final Scenario scenario;
    private final Controler controler;

    public static void main(String[] args) throws IOException {
        if (args.length < 3) {
            throw new IllegalArgumentException("Usage: <inputDir> <configName> <cleanNetwork>");
        }

        RunBaselineScenario rbs = new RunBaselineScenario(args[0], args[1], args[2]);
        rbs.run();
    }

    public RunBaselineScenario(String inputDir, String configName, String cleanNetwork) throws IOException {
        String configFile = inputDir + "/" + configName;

        this.config = ConfigUtils.loadConfig(configFile);

        this.config.controller().setOverwriteFileSetting(
                OutputDirectoryHierarchy.OverwriteFileSetting.deleteDirectoryIfExists
        );

        this.scenario = ScenarioUtils.loadScenario(config);
        if (Boolean.parseBoolean(cleanNetwork)) {
            System.out.println("About to clean the network");
            cleanNetworkForModes(this.scenario.getNetwork());
        }

        this.controler = new Controler(scenario);
    }

    private static void cleanNetworkForModes(Network network) {
        System.out.println("Normalising bike -> bicycle");

        network.getLinks().values().forEach(link -> {
            Set<String> modes = link.getAllowedModes();

            if (modes.contains("bike")) {
                Set<String> updatedModes = new java.util.HashSet<>(modes);
                updatedModes.remove("bike");
                updatedModes.add("bicycle");
                link.setAllowedModes(updatedModes);
            }
        });

        System.out.println("Applying bicycle dead-end filter");
        DeadEndFilter.clean(network);

        System.out.println("Cleaning bicycle network");

        new MultimodalNetworkCleaner(network).run(Set.of("bicycle"));

        System.out.println("Cleaning car network");

        new MultimodalNetworkCleaner(network).run(Set.of("car"));

        new NetworkWriter(network).write("./scenario/v1/networkCleaned.xml.gz");
    }

    public void run() {
        controler.addOverridingModule(new SBBTransitModule());
        controler.addOverridingModule(new SwissRailRaptorModule());
        controler.run();
    }
}
