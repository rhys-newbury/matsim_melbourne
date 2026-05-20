package io.github.matsimmelbourne.baseline.run;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Removes bicycle dead-ends from a MATSim network.
 *
 * Logic:
 *  - Filter only bicycle-enabled links
 *  - Find nodes with no bicycle in OR no bicycle out
 *  - If attached link is bicycle-only -> remove link
 *  - Otherwise remove bicycle from allowed modes
 *  - Repeat until stable
 */
public class DeadEndFilter {

    private static final Logger log = LogManager.getLogger(DeadEndFilter.class);

    private static final String MODE = "bicycle";

    public record RemovalAction(
            Id<Link> linkId,
            Id<Node> fromNode,
            Id<Node> toNode,
            String action,
            Set<String> oldModes,
            Set<String> newModes,
            String reason
    ) {}

    /**
     * Cleans bicycle dead ends.
     *
     * @param network MATSim network
     * @return list of actions taken
     */
    public static List<RemovalAction> clean(Network network) {

        List<RemovalAction> actions = new ArrayList<>();

        boolean changed;
        int iteration = 0;

        do {

            changed = false;
            iteration++;

            log.info("Starting bicycle dead-end cleanup iteration {}", iteration);

            List<Node> deadNodes = network.getNodes().values().stream()
                    .filter(DeadEndFilter::isDeadEnd)
                    .collect(Collectors.toList());

            long bikeNodes = network.getNodes().values().stream()
                    .filter(n -> !bikeIn(n).isEmpty() || !bikeOut(n).isEmpty())
                    .count();

            log.info("Bicycle nodes: {}, dead-end nodes: {}, share: {}%",
                    bikeNodes, deadNodes.size(), 100.0 * deadNodes.size() / bikeNodes);

            Set<Id<Link>> processedLinks = new HashSet<>();

            for (Node node : deadNodes) {

                Set<Link> incidentBikeLinks = new HashSet<>();
                incidentBikeLinks.addAll(bikeIn(node));
                incidentBikeLinks.addAll(bikeOut(node));

                for (Link link : incidentBikeLinks) {

                    if (!processedLinks.add(link.getId())) {
                        continue;
                    }

                    Set<String> oldModes = new HashSet<>(link.getAllowedModes());

                    // bicycle-only link -> remove entire link
                    if (oldModes.size() == 1 && oldModes.contains(MODE)) {

                        RemovalAction action = new RemovalAction(
                                link.getId(),
                                link.getFromNode().getId(),
                                link.getToNode().getId(),
                                "REMOVED_LINK",
                                Set.copyOf(oldModes),
                                Set.of(),
                                "bicycle dead-end; bicycle-only link"
                        );

                        actions.add(action);

                        logAction(action);

                        network.removeLink(link.getId());

                        changed = true;

                    } else if (oldModes.contains(MODE)) {

                        // mixed-mode link -> remove bicycle mode only
                        Set<String> newModes = new HashSet<>(oldModes);
                        newModes.remove(MODE);

                        RemovalAction action = new RemovalAction(
                                link.getId(),
                                link.getFromNode().getId(),
                                link.getToNode().getId(),
                                "REMOVED_BICYCLE",
                                Set.copyOf(oldModes),
                                Set.copyOf(newModes),
                                "bicycle dead-end; preserving other modes"
                        );

                        actions.add(action);

                        logAction(action);

                        link.setAllowedModes(newModes);

                        changed = true;
                    }
                }
            }

            // remove isolated nodes
            List<Id<Node>> emptyNodes = network.getNodes().values().stream()
                    .filter(n -> n.getInLinks().isEmpty() && n.getOutLinks().isEmpty())
                    .map(Node::getId)
                    .collect(Collectors.toList());

            emptyNodes.forEach(network::removeNode);

            if (!emptyNodes.isEmpty()) {
                log.info("Removed {} isolated nodes", emptyNodes.size());
            }

            log.info("Finished iteration {} with {} actions", iteration, actions.size());

        } while (changed);

        log.info("Bicycle dead-end cleanup complete. Total actions: {}", actions.size());

        return actions;
    }

    /**
     * A bicycle dead-end is:
     *  - no bicycle in
     *  OR
     *  - no bicycle out
     */
    private static boolean isDeadEnd(Node node) {
        return bikeIn(node).isEmpty() || bikeOut(node).isEmpty();
    }

    private static List<Link> bikeIn(Node node) {
        return node.getInLinks().values().stream()
                .filter(l -> l.getAllowedModes().contains(MODE))
                .collect(Collectors.toList());
    }

    private static List<Link> bikeOut(Node node) {
        return node.getOutLinks().values().stream()
                .filter(l -> l.getAllowedModes().contains(MODE))
                .collect(Collectors.toList());
    }

    private static void logAction(RemovalAction a) {

        log.info(
                "{} link={} from={} to={} oldModes={} newModes={} reason={}",
                a.action(),
                a.linkId(),
                a.fromNode(),
                a.toNode(),
                a.oldModes(),
                a.newModes(),
                a.reason()
        );
    }
}