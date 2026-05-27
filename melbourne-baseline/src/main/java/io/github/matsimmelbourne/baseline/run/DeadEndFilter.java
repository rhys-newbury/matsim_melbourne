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
 * Removes or repairs bicycle dead-ends from a MATSim network.
 *
 * Logic:
 *  - Filter only bicycle-enabled links
 *  - Find nodes with no bicycle in OR no bicycle out
 *  - If addReverseLinks == false:
 *      - bicycle-only links are removed
 *      - mixed-mode links lose bicycle mode
 *  - If addReverseLinks == true:
 *      - a reverse bicycle link is added instead
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
     * Existing behaviour: cleans bicycle dead ends by removing them.
     *
     * @param network MATSim network
     * @return list of actions taken
     */
    public static List<RemovalAction> clean(Network network) {
        return clean(network, false);
    }

    /**
     * Cleans or repairs bicycle dead ends.
     *
     * @param network MATSim network
     * @param addReverseLinks if true, add reverse bicycle links instead of removing dead ends
     * @return list of actions taken
     */
    public static List<RemovalAction> clean(Network network, boolean addReverseLinks) {

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

            if (bikeNodes == 0) {
                log.info("No bicycle nodes remaining");
                break;
            }

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

                    if (!oldModes.contains(MODE)) {
                        continue;
                    }

                    if (addReverseLinks) {

                        boolean added = addReverseBikeLink(network, link, actions);

                        if (added) {
                            changed = true;
                        }

                    } else if (oldModes.size() == 1 && oldModes.contains(MODE)) {

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

                    } else {

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

            if (!addReverseLinks) {
                List<Id<Node>> emptyNodes = network.getNodes().values().stream()
                        .filter(n -> n.getInLinks().isEmpty() && n.getOutLinks().isEmpty())
                        .map(Node::getId)
                        .collect(Collectors.toList());

                emptyNodes.forEach(network::removeNode);

                if (!emptyNodes.isEmpty()) {
                    log.info("Removed {} isolated nodes", emptyNodes.size());
                }
            }

            log.info("Finished iteration {} with {} actions", iteration, actions.size());

        } while (changed);

        log.info("Bicycle dead-end cleanup complete. Total actions: {}", actions.size());

        return actions;
    }

    /**
     * Adds a reverse bicycle link from B -> A for a dead-end A -> B link.
     */
    private static boolean addReverseBikeLink(
            Network network,
            Link originalLink,
            List<RemovalAction> actions
    ) {

        Id<Link> reverseId = Id.createLinkId(originalLink.getId() + "_reverse");

        if (network.getLinks().containsKey(reverseId)) {
            return false;
        }

        Node fromNode = originalLink.getToNode();
        Node toNode = originalLink.getFromNode();

        Link reverseLink = network.getFactory().createLink(
                reverseId,
                fromNode,
                toNode
        );

        reverseLink.setAllowedModes(Set.of(MODE));
        reverseLink.setLength(originalLink.getLength());
        reverseLink.setFreespeed(originalLink.getFreespeed());
        reverseLink.setCapacity(originalLink.getCapacity());
        reverseLink.setNumberOfLanes(originalLink.getNumberOfLanes());

        network.addLink(reverseLink);

        RemovalAction action = new RemovalAction(
                reverseLink.getId(),
                reverseLink.getFromNode().getId(),
                reverseLink.getToNode().getId(),
                "ADDED_REVERSE_LINK",
                Set.of(),
                Set.of(MODE),
                "bicycle dead-end repaired by adding reverse link"
        );

        actions.add(action);
        logAction(action);

        return true;
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